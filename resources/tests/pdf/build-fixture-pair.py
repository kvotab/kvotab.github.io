# -*- coding: utf-8 -*-
"""Build one fixture report as both .docx and .pdf.

The point of the pair is that the .docx is the oracle. Its structure is stated
outright by the file format, so whatever the checker reports for the .docx is
by construction the right answer for that text. The .pdf carries exactly the
same words, so any difference in the two reports is a defect in the PDF
reconstruction and nowhere else.

The fixture is built to be hostile to the reconstruction on purpose:

  * a running header and a page number on every page, which must be stripped,
    because they are not in the .docx and would otherwise show up as extra text
  * paragraphs that wrap across lines and across pages
  * a reference list set with a hanging indent, entries wrapping to two lines
  * a line broken on a typesetter's hyphen (radio-active) and one broken on a
    real compound hyphen (SKB-rapport), which must be rejoined differently
  * an italic run and a superscript, neither of which is a text attribute in a
    PDF
  * headings distinguished from body text only by their size

Usage:  python3 build-fixture-pair.py [outdir]
"""
import io
import json
import os
import sys
import zlib
import zipfile
import html

# --------------------------------------------------------------------------
# The document, written once.
#
# Each block is (kind, runs); a run is (text, fmt) with fmt in
# '' | 'i' | 'b' | 'sup' | 'sub'.  Kinds: h1 h2 body ref pagebreak
# --------------------------------------------------------------------------

BLOCKS = [
    ('h1', [('Hydrogeological modelling of the repository', '')]),
    ('h2', [('1 Introduction', '')]),
    ('body', [('The hydrogeological model of the Forsmark site has been developed over '
               'several stages, and the most recent revision is documented in the site '
               'descriptive model (Andersson and Berglund 2010). Flow paths through the '
               'fracture network were recalculated for the present assessment.', '')]),
    ('body', [('Measurements of ', ''), ('14', 'sup'), ('C in the groundwater support the '
               'residence times reported earlier (SKB TR-14-09). The species ', ''),
              ('Desulfovibrio aespoeensis', 'i'), (' was identified in the same samples.', '')]),
    # "radio-active" breaks on a typesetter's hyphen and must be rejoined;
    # "SKB-rapport" breaks on a real one and must keep it.
    ('body', [('Waste from the encapsulation plant is classified as radioactive and is '
               'handled under the routines described in the SKB-rapport series, which '
               'the regulator reviews at each stage of the licensing process.', '')]),
    ('body', [('The regulations (SSMFS 2008:37) specify the dose constraint applied '
               'throughout this report.', '')]),
    # Ordinary spaces where the guides require non-breaking ones. The .docx run
    # must report all three; the PDF run must report none of them, because a PDF
    # does not record which kind of space was set.
    ('body', [('The measured temperature was 12 \u00b0C and the porosity 0.5 % at a depth '
               'of 470 m, which agrees with the earlier interpretation of the site.', '')]),
    ('pagebreak', []),
    ('h2', [('2 Method', '')]),
    ('body', [('Particle tracking was performed with the same code as in the previous '
               'assessment (Follin et al. 2008). No changes were made to the boundary '
               'conditions.', '')]),
    ('body', [('An earlier interpretation of the deformation zones (Nilsson 1998) was '
               'not used, because the geometry has since been revised.', '')]),
    ('pagebreak', []),
    ('h2', [('References', '')]),
    ('ref', [('Andersson J, Berglund S, 2010. Groundwater flow modelling in fractured '
              'rock at the Forsmark site. SKB R-10-11, Svensk Karnbranslehantering AB.', '')]),
    ('ref', [('Follin S, Levén J, Hartley L, Jackson P, Joyce S, Roberts D, Swift B, '
              '2008. Hydrogeological characterisation and modelling of deformation '
              'zones and fracture domains. SKB R-08-95, Svensk Karnbranslehantering AB.', '')]),
    ('ref', [('Nilsson G, 1998. An earlier interpretation of the deformation zones. '
              'SKB R-98-11, Svensk Karnbranslehantering AB.', '')]),
    ('ref', [('SKB, 2014. Safety analysis for SFR. Long-term safety. SKB TR-14-09, '
              'Svensk Karnbranslehantering AB.', '')]),
    ('ref', [('SSMFS 2008:37. Stralsakerhetsmyndighetens foreskrifter om skydd av '
              'manniskors halsa. Stockholm: Stralsakerhetsmyndigheten. (In Swedish.)', '')]),
    ('ref', [('Wyllie D C, Mah C W, 2004. Rock slope engineering: civil and mining. '
              '4th ed. New York: Spon Press.', '')]),
]

RUNNING_HEADER = 'SKB TR-25-01  Hydrogeological modelling of the repository'

# --------------------------------------------------------------------------
# .docx
# --------------------------------------------------------------------------

CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
      '</Types>')

RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')

DOCRELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
           '</Relationships>')

STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
          '<w:docDefaults><w:rPrDefault><w:rPr><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
          '</w:styles>')


def docx_run(text, fmt):
    props = '<w:lang w:val="en-GB"/>'
    if fmt == 'sup':
        props += '<w:vertAlign w:val="superscript"/>'
    if fmt == 'sub':
        props += '<w:vertAlign w:val="subscript"/>'
    if fmt == 'i':
        props += '<w:i/>'
    if fmt == 'b':
        props += '<w:b/>'
    return ('<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
            % (props, html.escape(text)))


def build_docx(path):
    style_for = {'h1': 'Heading1', 'h2': 'Heading2'}
    body = ''
    for kind, runs in BLOCKS:
        if kind == 'pagebreak':
            continue
        pPr = ''
        if kind in style_for:
            pPr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style_for[kind]
        body += '<w:p>' + pPr + ''.join(docx_run(t, f) for t, f in runs) + '</w:p>'
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>%s</w:body></w:document>' % body)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', CT)
        archive.writestr('_rels/.rels', RELS)
        archive.writestr('word/_rels/document.xml.rels', DOCRELS)
        archive.writestr('word/styles.xml', STYLES)
        archive.writestr('word/document.xml', doc)
    return path


# --------------------------------------------------------------------------
# .pdf
#
# Written by hand rather than with a library, because the fixture's value is in
# controlling the geometry exactly: the indents, the leading and the line breaks
# are the input the reconstruction is being tested on.
# --------------------------------------------------------------------------

# Helvetica advance widths, units per 1000. Body text is set in the regular
# face, so wrapping and the right-hand edge of every body line are exact.
HELVETICA = {
    ' ': 278, '!': 278, '"': 355, '#': 556, '$': 556, '%': 889, '&': 667, "'": 191,
    '(': 333, ')': 333, '*': 389, '+': 584, ',': 278, '-': 333, '.': 278, '/': 278,
    ':': 278, ';': 278, '<': 584, '=': 584, '>': 584, '?': 556, '@': 1015,
    'A': 667, 'B': 667, 'C': 722, 'D': 722, 'E': 667, 'F': 611, 'G': 778, 'H': 722,
    'I': 278, 'J': 500, 'K': 667, 'L': 556, 'M': 833, 'N': 722, 'O': 778, 'P': 667,
    'Q': 778, 'R': 722, 'S': 667, 'T': 611, 'U': 722, 'V': 667, 'W': 944, 'X': 667,
    'Y': 667, 'Z': 611, '[': 278, '\\': 278, ']': 278, '^': 469, '_': 556, '`': 333,
    'a': 556, 'b': 556, 'c': 500, 'd': 556, 'e': 556, 'f': 278, 'g': 556, 'h': 556,
    'i': 222, 'j': 222, 'k': 500, 'l': 222, 'm': 833, 'n': 556, 'o': 556, 'p': 556,
    'q': 556, 'r': 333, 's': 500, 't': 278, 'u': 556, 'v': 500, 'w': 722, 'x': 500,
    'y': 500, 'z': 500, '{': 334, '|': 260, '}': 334, '~': 584,
}
for _digit in '0123456789':
    HELVETICA[_digit] = 556


def width_of(text, size):
    return sum(HELVETICA.get(ch, 556) for ch in text) * size / 1000.0


PAGE_W, PAGE_H = 595.0, 842.0
LEFT, RIGHT = 70.0, 525.0
TOP, BOTTOM = 780.0, 90.0
BODY_SIZE, LEADING = 10.0, 13.0
SIZE_FOR = {'h1': 18.0, 'h2': 14.0, 'body': BODY_SIZE, 'ref': BODY_SIZE}
FONT_FOR = {'': 'F1', 'i': 'F2', 'b': 'F3', 'sup': 'F1', 'sub': 'F1'}
REF_HANG = 22.0          # continuation lines of a reference are indented


def wrap_runs(runs, size, first_width, rest_width):
    """Wrap (text, fmt) runs into lines of (text, fmt, dx) pieces."""
    words = []
    for text, fmt in runs:
        parts = text.split(' ')
        for position, part in enumerate(parts):
            if part == '' and position not in (0, len(parts) - 1):
                continue
            words.append((part, fmt, position == 0 and words and not text.startswith(' ')))
    lines, current, used = [], [], 0.0
    limit = first_width
    for word, fmt, glued in words:
        run_size = size * 0.62 if fmt in ('sup', 'sub') else size
        advance = width_of(word, run_size)
        space = 0.0 if (not current or glued) else width_of(' ', size)
        if current and used + space + advance > limit:
            lines.append(current)
            current, used, limit = [], 0.0, rest_width
            space = 0.0
        current.append((word, fmt, space))
        used += space + advance
    if current:
        lines.append(current)
    return lines


def layout():
    """Return [{'width','height','lines':[(x, baseline, [(text,fmt,size)])]}]."""
    pages, lines = [], []
    y = TOP

    def flush():
        pages.append(lines[:])
        del lines[:]

    for kind, runs in BLOCKS:
        if kind == 'pagebreak':
            flush()
            y = TOP
            continue
        size = SIZE_FOR[kind]
        leading = LEADING if kind in ('body', 'ref') else size * 1.35
        gap = 0.0 if kind == 'ref' else leading * 0.6
        first_x = LEFT
        rest_x = LEFT + REF_HANG if kind == 'ref' else LEFT
        wrapped = wrap_runs(runs, size, RIGHT - first_x, RIGHT - rest_x)
        y -= gap
        for index, pieces in enumerate(wrapped):
            if y < BOTTOM:
                flush()
                y = TOP
            x = first_x if index == 0 else rest_x
            placed, cursor = [], x
            for word, fmt, space in pieces:
                cursor += space
                run_size = size * 0.62 if fmt in ('sup', 'sub') else size
                dy = size * 0.33 if fmt == 'sup' else (-size * 0.17 if fmt == 'sub' else 0.0)
                placed.append((cursor, y + dy, word, fmt, run_size))
                cursor += width_of(word, run_size)
            lines.append(placed)
            y -= leading
    flush()
    return pages


def escape_pdf(text):
    return text.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')


def content_stream(placed_lines, page_number):
    out = ['BT']
    # The running header and the page number: present on every page, and part of
    # neither the .docx nor the text of the report.
    out.append('/F1 8 Tf 1 0 0 1 %.2f %.2f Tm (%s) Tj' % (LEFT, 806.0, escape_pdf(RUNNING_HEADER)))
    number = str(page_number)
    out.append('/F1 9 Tf 1 0 0 1 %.2f %.2f Tm (%s) Tj'
               % (PAGE_W / 2 - width_of(number, 9) / 2, 45.0, number))
    for placed in placed_lines:
        for x, baseline, word, fmt, size in placed:
            out.append('/%s %.2f Tf 1 0 0 1 %.2f %.2f Tm (%s) Tj'
                       % (FONT_FOR[fmt], size, x, baseline, escape_pdf(word)))
    out.append('ET')
    return '\n'.join(out).encode('latin-1', 'replace')


def build_pdf(path):
    pages = layout()
    objects = {}
    font_objects = {'F1': 20, 'F2': 21, 'F3': 22}
    base_font = {'F1': 'Helvetica', 'F2': 'Helvetica-Oblique', 'F3': 'Helvetica-Bold'}

    page_ids = [10 + index * 2 for index in range(len(pages))]
    kids = ' '.join('%d 0 R' % pid for pid in page_ids)
    objects[1] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[2] = ('<< /Type /Pages /Kids [%s] /Count %d >>' % (kids, len(pages))).encode()

    resources = ('<< /Font << %s >> >>'
                 % ' '.join('/%s %d 0 R' % (name, oid) for name, oid in font_objects.items()))
    for index, placed_lines in enumerate(pages):
        page_id, content_id = page_ids[index], page_ids[index] + 1
        objects[page_id] = ('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.0f %.0f] '
                            '/Resources %s /Contents %d 0 R >>'
                            % (PAGE_W, PAGE_H, resources, content_id)).encode()
        raw = content_stream(placed_lines, index + 1)
        packed = zlib.compress(raw)
        objects[content_id] = (b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(packed)
                               + packed + b'\nendstream')

    for name, oid in font_objects.items():
        objects[oid] = ('<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>'
                        % base_font[name]).encode()

    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += b'%d 0 obj\n' % oid + objects[oid] + b'\nendobj\n'

    highest = max(objects) + 1
    xref_at = len(out)
    out += b'xref\n0 %d\n' % highest
    out += b'0000000000 65535 f \n'
    for oid in range(1, highest):
        out += (b'%010d 00000 n \n' % offsets[oid]) if oid in offsets else b'0000000000 65535 f \n'
    out += (b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
            % (highest, xref_at))

    with open(path, 'wb') as handle:
        handle.write(bytes(out))
    return path, len(pages)


def dump_items(path):
    """The item stream pdf.js would produce, for the Node geometry tests.

    Written from the same layout() the PDF is drawn from, so the two agree by
    construction; it lets the reconstruction be tested without a browser.
    """
    pages = []
    line_pages = []
    for index, placed_lines in enumerate(layout()):
        items = [{
            'str': RUNNING_HEADER, 'x': LEFT, 'y': 806.0,
            'width': width_of(RUNNING_HEADER, 8), 'fontSize': 8.0,
            'bold': False, 'italic': False
        }, {
            'str': str(index + 1), 'x': PAGE_W / 2 - width_of(str(index + 1), 9) / 2,
            'y': 45.0, 'width': width_of(str(index + 1), 9), 'fontSize': 9.0,
            'bold': False, 'italic': False
        }]
        for placed in placed_lines:
            for x, baseline, word, fmt, size in placed:
                items.append({
                    'str': word, 'x': x, 'y': baseline,
                    'width': width_of(word, size), 'fontSize': size,
                    'bold': fmt == 'b', 'italic': fmt == 'i'
                })
        pages.append({'pageNumber': index + 1, 'width': PAGE_W, 'height': PAGE_H, 'items': items})

        # pdf.js splits a line into items wherever the kerning changes, so the
        # same PDF may arrive one word at a time or one whole line at a time.
        # Both granularities are emitted, because the reconstruction has to
        # cope with either and they exercise different code.
        merged = list(items[:2])
        for placed in placed_lines:
            words = [(x, base, word, fmt, size) for x, base, word, fmt, size in placed]
            body = [w for w in words if w[3] not in ('sup', 'sub')]
            if not body:
                body = words
            text = ''
            cursor = None
            for x, base, word, fmt, size in words:
                if cursor is not None and x - cursor > 0.22 * size:
                    text += ' '
                text += word
                cursor = x + width_of(word, size)
            first = body[0]
            last = words[-1]
            merged.append({
                'str': text, 'x': words[0][0], 'y': first[1],
                'width': last[0] + width_of(last[2], last[4]) - words[0][0],
                'fontSize': first[4], 'bold': first[3] == 'b', 'italic': first[3] == 'i'
            })
        line_pages.append({'pageNumber': index + 1, 'width': PAGE_W, 'height': PAGE_H, 'items': merged})

    # The paragraph texts the .docx yields, which the reconstruction must match.
    expected = []
    for kind, runs in BLOCKS:
        if kind == 'pagebreak':
            continue
        expected.append({'kind': kind, 'text': ''.join(text for text, _ in runs).strip()})

    with io.open(path, 'w', encoding='utf-8') as handle:
        json.dump({'pages': pages, 'pagesByLine': line_pages, 'expected': expected},
                  handle, ensure_ascii=False, indent=1)
    return path


def build_scan(path):
    """A PDF with a page but no text layer: what a scan looks like to a reader.

    Analysing one would report a document with no references and no citations,
    which reads as a clean bill of health rather than as a file that cannot be
    checked, so the reader has to refuse it outright.
    """
    content = b'0.5 0.5 0.5 rg 100 100 300 400 re f'      # a grey box, no text
    packed = zlib.compress(content)
    objects = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        2: b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        3: ('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.0f %.0f] /Resources << >> '
            '/Contents 4 0 R >>' % (PAGE_W, PAGE_H)).encode(),
        4: (b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(packed)
            + packed + b'\nendstream'),
    }
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += b'%d 0 obj\n' % oid + objects[oid] + b'\nendobj\n'
    highest = max(objects) + 1
    xref_at = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % highest
    for oid in range(1, highest):
        out += b'%010d 00000 n \n' % offsets[oid]
    out += (b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
            % (highest, xref_at))
    with open(path, 'wb') as handle:
        handle.write(bytes(out))
    return path


if __name__ == '__main__':
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    docx_path = build_docx(os.path.join(outdir, 'fixture-report.docx'))
    pdf_path, page_count = build_pdf(os.path.join(outdir, 'fixture-report.pdf'))
    print('wrote %s' % docx_path)
    print('wrote %s (%d pages)' % (pdf_path, page_count))
    print('wrote %s' % dump_items(os.path.join(outdir, 'fixture-items.json')))
    print('wrote %s' % build_scan(os.path.join(outdir, 'fixture-scan-no-text.pdf')))
