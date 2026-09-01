"""Build a .docx whose runs carry real character formatting."""
import zipfile
import html
import sys

CT = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''

RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

DOCRELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/><w:rPr><w:lang w:val="en-GB"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:lang w:val="en-GB"/></w:rPr></w:style>
</w:styles>'''


def run(text, fmt=''):
    """fmt may contain: sup, sub, i, u"""
    props = '<w:lang w:val="en-GB"/>'
    if 'sup' in fmt:
        props += '<w:vertAlign w:val="superscript"/>'
    if 'sub' in fmt:
        props += '<w:vertAlign w:val="subscript"/>'
    if 'i' in fmt.split(','):
        props += '<w:i/>'
    if 'u' in fmt.split(','):
        props += '<w:u w:val="single"/>'
    return ('<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
            % (props, html.escape(text)))


def para(runs, style=None):
    body = '<w:p>'
    if style:
        body += '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style
    for text, fmt in runs:
        body += run(text, fmt)
    return body + '</w:p>'


def build(paragraphs, out):
    body = ''.join(para(runs, style) for runs, style in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>%s</w:body></w:document>' % body)
    z = zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED)
    z.writestr('[Content_Types].xml', CT)
    z.writestr('_rels/.rels', RELS)
    z.writestr('word/_rels/document.xml.rels', DOCRELS)
    z.writestr('word/styles.xml', STYLES)
    z.writestr('word/document.xml', doc)
    z.close()
    print('wrote', out)


PARAS = [
    ([('Formatting test', '')], 'Heading1'),

    # --- CORRECT: subscripts, superscripts and italics as the guide requires ---
    ([('The solution contained H', ''), ('2', 'sub'), ('SO', ''), ('4', 'sub'),
      (' and CaCO', ''), ('3', 'sub'), (' at equilibrium.', '')], None),
    ([('The isotopes ', ''), ('37', 'sup'), ('Cl and ', ''), ('59', 'sup'),
      ('Ni were measured.', '')], None),
    ([('The result follows from the model, where ', ''), ('V', 'i'),
      (' is the volume of the pore space.', '')], None),
    ([('The identifiers SFR1, CCP33 and KBS3 appear throughout.', '')], None),

    # --- ERRORS ---
    ([('ERRORS BELOW', '')], 'Heading1'),
    ([('The solution contained H2SO4 and CaCO3 without subscripts.', '')], None),
    ([('The isotopes 37Cl and 59Ni were written without superscripts.', '')], None),
    ([('This follows from the model, where V is the volume of the pore space.', '')], None),
    ([('This sentence contains ', ''), ('underlined text', 'u'),
      (' which the handbook forbids.', '')], None),

    # --- reference list, with a superscript edition ordinal ---
    ([('References', '')], 'Heading1'),
    ([('Ahlbom K, 1991. A study of rock. SKB TR-91-01, Svensk Karnbranslehantering AB.', '')], None),
    ([('Wyllie D C, Mah C W, 2004. Rock slope engineering: civil and mining. 4', ''),
      ('th', 'sup'), (' ed. New York: Spon Press.', '')], None),
    ([('Bengtsson A, 1999. An earlier study. SKB R-99-11, Svensk Karnbranslehantering AB.', '')], None),
]

if __name__ == '__main__':
    build(PARAS, sys.argv[1] if len(sys.argv) > 1 else 'skb-format-test.docx')
