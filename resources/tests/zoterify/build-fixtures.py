#!/usr/bin/env python3
"""Build the fixtures for zoterify.html's tests.

    python3 build-fixtures.py            # writes fixtures/ next to this file

fixtures/fixture.sqlite
    A small Zotero database with the tables and columns Zotero 7 has for
    what the page reads: a user library (synced, userID 4242), a group
    library (groupID 777), a feed, collections, a deleted item, an
    attachment, a note and an annotation that must all be left out.

fixtures/fixture-wal.sqlite, fixtures/fixture-wal.sqlite-wal
    The same database in WAL mode, copied while one more item (Stone 2018)
    was committed to the -wal file and not yet to the database: read alone
    it has no Stone, read with its -wal file it has.

fixtures/fixture.docx
    A document that walks the writer through every case it must handle;
    see PARAGRAPHS below. Its runs, fields, revisions and parts are written
    out by hand so each case is exactly what it says.
"""
import os
import shutil
import sqlite3
import tempfile
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'fixtures')

# --------------------------------------------------------------------------
# The Zotero database
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT NOT NULL, editable INT NOT NULL, filesEditable INT NOT NULL,
  version INT NOT NULL DEFAULT 0, storageVersion INT NOT NULL DEFAULT 0, lastSync INT NOT NULL DEFAULT 0, archived INT NOT NULL DEFAULT 0);
CREATE TABLE groups (groupID INTEGER PRIMARY KEY, libraryID INT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', version INT NOT NULL DEFAULT 0);
CREATE TABLE settings (setting TEXT, key TEXT, value, PRIMARY KEY (setting, key));
CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT, templateItemTypeID INT, display INT DEFAULT 1);
CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT, fieldFormatID INT);
CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
CREATE TABLE itemTypeCreatorTypes (itemTypeID INT, creatorTypeID INT, primaryField INT, PRIMARY KEY (itemTypeID, creatorTypeID));
CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT NOT NULL, dateAdded TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  dateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, clientDateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  libraryID INT NOT NULL, key TEXT NOT NULL, version INT NOT NULL DEFAULT 0, synced INT NOT NULL DEFAULT 0, UNIQUE (libraryID, key));
CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value UNIQUE);
CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT, PRIMARY KEY (itemID, fieldID));
CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, fieldMode INT, UNIQUE (lastName, firstName, fieldMode));
CREATE TABLE itemCreators (itemID INT NOT NULL, creatorID INT NOT NULL, creatorTypeID INT NOT NULL DEFAULT 1, orderIndex INT NOT NULL DEFAULT 0,
  PRIMARY KEY (itemID, creatorID, creatorTypeID, orderIndex), UNIQUE (itemID, orderIndex));
CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY, dateDeleted DEFAULT CURRENT_TIMESTAMP NOT NULL);
CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT NOT NULL, clientDateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  libraryID INT NOT NULL, key TEXT NOT NULL, parentCollectionID INT DEFAULT NULL);
CREATE TABLE collectionItems (collectionID INT NOT NULL, itemID INT NOT NULL, orderIndex INT NOT NULL DEFAULT 0, PRIMARY KEY (collectionID, itemID));
CREATE TABLE deletedCollections (collectionID INTEGER PRIMARY KEY, dateDeleted DEFAULT CURRENT_TIMESTAMP NOT NULL);
"""

ITEM_TYPES = {1: 'annotation', 2: 'attachment', 3: 'book', 4: 'bookSection', 5: 'journalArticle', 6: 'note',
              7: 'report', 8: 'computerProgram', 9: 'case'}
FIELDS = {1: 'title', 2: 'date', 3: 'publicationTitle', 4: 'volume', 5: 'pages', 6: 'DOI', 7: 'publisher',
          8: 'reportNumber', 9: 'place', 10: 'accessDate', 11: 'url', 12: 'caseName', 13: 'dateDecided', 14: 'extra'}
CREATOR_TYPES = {1: 'author', 2: 'editor', 3: 'seriesEditor', 4: 'programmer', 5: 'translator'}
PRIMARY = [(3, 1), (4, 1), (5, 1), (7, 1), (8, 4), (9, 1)]

# itemID, library, type, key, dateAdded, fields, creators [(last, first, type, fieldMode)]
ITEMS = [
    (10, 1, 5, 'SMITH020', '2024-01-10 10:00:00', {'title': 'Buffer erosion in dilute groundwater', 'date': '2020-03-00 March 2020',
      'publicationTitle': 'Applied Clay Science', 'volume': '185', 'pages': '105-117', 'DOI': '10.1000/aclay.2020.1'},
     [('Smith', 'John', 'author', 0)]),
    (11, 1, 5, 'JONES20A', '2024-01-11 10:00:00', {'title': 'Sulphide transport in fractured rock', 'date': '2020-00-00 2020',
      'publicationTitle': 'Journal of Hydrology'}, [('Jones', 'Anna', 'author', 0)]),
    (12, 1, 5, 'JONES20B', '2024-01-12 10:00:00', {'title': 'Copper corrosion under reducing conditions', 'date': '2020-11-02 2020-11-02',
      'publicationTitle': 'Corrosion Science'}, [('Jones', 'Anna', 'author', 0)]),
    (13, 1, 7, 'BROWN019', '2024-01-13 10:00:00', {'title': 'Groundwater flow at Forsmark', 'date': '2019-00-00 2019',
      'reportNumber': 'R-19-01', 'publisher': 'Svensk Kärnbränslehantering AB', 'place': 'Stockholm'},
     [('Brown', 'Peter', 'author', 0), ('Svensk Kärnbränslehantering AB', '', 'seriesEditor', 1)]),
    (14, 1, 5, 'GARCI021', '2024-01-14 10:00:00', {'title': 'Radionuclide sorption on bentonite', 'date': '2021-00-00 2021'},
     [('Garcia', 'Maria', 'author', 0), ('Lopez', 'Juan', 'author', 0)]),
    (15, 2, 7, 'OHMAN014', '2024-01-15 10:00:00', {'title': 'Hydrogeological modelling of SFR', 'date': '2014-00-00 2014',
      'reportNumber': 'R-13-25', 'publisher': 'Svensk Kärnbränslehantering AB'},
     [('Öhman', 'Johan', 'author', 0), ('Odén', 'Magnus', 'author', 0), ('Vidstrand', 'Patrik', 'author', 0)]),
    (16, 2, 3, 'LANE0014', '2024-01-16 10:00:00', {'title': 'The culture of quality', 'date': '2014-00-00 2014', 'publisher': 'Routledge'},
     [('Lane', 'Christel', 'author', 0)]),
    (17, 1, 5, 'BILDT010', '2024-01-17 10:00:00', {'title': 'Taste and distinction', 'date': '2010-00-00 2010'},
     [('Bildtgård', 'Torbjörn', 'author', 0)]),
    (18, 1, 8, 'PROGR022', '2024-01-18 10:00:00', {'title': 'A transport code', 'date': '2022-00-00 2022'},
     [('Programmer', 'Pat', 'programmer', 0)]),
    (19, 1, 9, 'CASE2003', '2024-01-19 10:00:00', {'caseName': 'Example v. Sample', 'dateDecided': '2003-05-01 2003-05-01'},
     [('Court', 'High', 'author', 0)]),
    # two papers by one author in one year, neither in the document's reference list: a choice
    (21, 1, 5, 'NILSS15A', '2024-01-21 10:00:00', {'title': 'Bentonite swelling pressure', 'date': '2015-00-00 2015'},
     [('Nilsson', 'Magnus', 'author', 0)]),
    (22, 1, 5, 'NILSS15B', '2024-01-22 10:00:00', {'title': 'Bentonite erosion rates', 'date': '2015-00-00 2015'},
     [('Nilsson', 'Magnus', 'author', 0)]),
    # left out: attachment, note, annotation, a deleted item, a feed item
    (30, 1, 2, 'ATTACH01', '2024-01-20 10:00:00', {'title': 'Smith 2020.pdf'}, []),
    (31, 1, 6, 'NOTE0001', '2024-01-20 10:00:00', {}, []),
    (32, 1, 1, 'ANNOT001', '2024-01-20 10:00:00', {}, []),
    (33, 1, 5, 'DELETED1', '2024-01-20 10:00:00', {'title': 'Deleted', 'date': '2020-00-00 2020'}, [('Smith', 'Old', 'author', 0)]),
    (34, 3, 5, 'FEEDITEM', '2024-01-20 10:00:00', {'title': 'Feed', 'date': '2020-00-00 2020'}, [('Smith', 'Feed', 'author', 0)]),
]
STONE = (20, 1, 5, 'STONE018', '2024-02-01 10:00:00', {'title': 'Quality conventions', 'date': '2018-00-00 2018'},
         [('Stone', 'Ann', 'author', 0), ('Rees', 'Bo', 'author', 0), ('Wu', 'Chen', 'author', 0)])


def insert_item(c, item):
    item_id, lib, typ, key, added, fields, creators = item
    c.execute('INSERT INTO items (itemID, itemTypeID, dateAdded, libraryID, key) VALUES (?,?,?,?,?)', (item_id, typ, added, lib, key))
    fid = {v: k for k, v in FIELDS.items()}
    for name, value in fields.items():
        c.execute('INSERT OR IGNORE INTO itemDataValues (value) VALUES (?)', (value,))
        vid = c.execute('SELECT valueID FROM itemDataValues WHERE value = ?', (value,)).fetchone()[0]
        c.execute('INSERT INTO itemData VALUES (?,?,?)', (item_id, fid[name], vid))
    ctid = {v: k for k, v in CREATOR_TYPES.items()}
    for order, (last, first, ctype, mode) in enumerate(creators):
        c.execute('INSERT OR IGNORE INTO creators (firstName, lastName, fieldMode) VALUES (?,?,?)', (first, last, mode))
        cid = c.execute('SELECT creatorID FROM creators WHERE lastName = ? AND firstName = ? AND fieldMode = ?', (last, first, mode)).fetchone()[0]
        c.execute('INSERT INTO itemCreators VALUES (?,?,?,?)', (item_id, cid, ctid[ctype], order))


def fill(c):
    c.executescript(SCHEMA)
    c.executemany('INSERT INTO libraries (libraryID, type, editable, filesEditable) VALUES (?,?,1,1)', [(1, 'user'), (2, 'group'), (3, 'feed')])
    c.execute("INSERT INTO groups (groupID, libraryID, name) VALUES (777, 2, 'Team references')")
    c.executemany('INSERT INTO settings VALUES (?,?,?)', [('account', 'userID', 4242), ('account', 'localUserKey', 'LOCALKEY'), ('account', 'username', 'tester')])
    c.executemany('INSERT INTO itemTypes (itemTypeID, typeName) VALUES (?,?)', ITEM_TYPES.items())
    c.executemany('INSERT INTO fields (fieldID, fieldName) VALUES (?,?)', FIELDS.items())
    c.executemany('INSERT INTO creatorTypes VALUES (?,?)', CREATOR_TYPES.items())
    c.executemany('INSERT INTO itemTypeCreatorTypes VALUES (?,?,1)', PRIMARY)
    for item in ITEMS:
        insert_item(c, item)
    c.execute('INSERT INTO deletedItems (itemID) VALUES (33)')
    c.executemany('INSERT INTO collections (collectionID, collectionName, libraryID, key, parentCollectionID) VALUES (?,?,?,?,?)',
                  [(1, 'Thesis', 1, 'COLL0001', None), (2, 'Chapter 2', 1, 'COLL0002', 1), (3, 'Binned', 1, 'COLL0003', None),
                   (4, 'Site data', 2, 'COLL0004', None)])
    c.execute('INSERT INTO deletedCollections (collectionID) VALUES (3)')
    c.executemany('INSERT INTO collectionItems (collectionID, itemID) VALUES (?,?)', [(1, 10), (2, 11), (2, 12), (3, 13), (4, 15), (1, 33)])


def build_databases():
    path = os.path.join(OUT, 'fixture.sqlite')
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path)
    fill(c)
    c.commit()
    c.execute('VACUUM')
    c.close()

    tmp = tempfile.mkdtemp()
    live = os.path.join(tmp, 'z.sqlite')
    c = sqlite3.connect(live, isolation_level=None)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA wal_autocheckpoint=0')
    fill(c)   # executescript() commits by itself
    c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    c.execute('BEGIN')
    insert_item(c, STONE)
    c.execute('COMMIT')
    shutil.copyfile(live, os.path.join(OUT, 'fixture-wal.sqlite'))
    shutil.copyfile(live + '-wal', os.path.join(OUT, 'fixture-wal.sqlite-wal'))
    c.close()
    shutil.rmtree(tmp)


# --------------------------------------------------------------------------
# The Word document
# --------------------------------------------------------------------------

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def t(text):
    return f'<w:t xml:space="preserve">{escape(text)}</w:t>'


def r(text, props=''):
    return f'<w:r>{"<w:rPr>" + props + "</w:rPr>" if props else ""}{t(text)}</w:r>'


def p(*content, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    return f'<w:p>{ppr}{"".join(content)}</w:p>'


def field(instr, result_runs, nested=''):
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{escape(instr)}</w:instrText></w:r>{nested}'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'{result_runs}<w:r><w:fldChar w:fldCharType="end"/></w:r>')


ZOTERO_EXISTING = (' ADDIN ZOTERO_ITEM CSL_CITATION {"citationID":"old1","properties":{"formattedCitation":"(Lane, 2014)",'
                   '"plainCitation":"(Lane, 2014)","noteIndex":0},"citationItems":[{"id":16,"uris":["http://zotero.org/groups/777/items/LANE0014"],'
                   '"itemData":{"id":16,"type":"book","title":"The culture of quality","author":[{"family":"Lane","given":"Christel"}],'
                   '"issued":{"date-parts":[["2014"]]}}}],"schema":"https://github.com/citation-style-language/schema/raw/master/csl-citation.json"} ')
ENDNOTE = ' ADDIN EN.CITE <EndNote><Cite><Author>Brown</Author><Year>2019</Year><RecNum>7</RecNum></Cite></EndNote>'
ENDNOTE_DATA = ('<w:r><w:fldChar w:fldCharType="begin"><w:fldData xml:space="preserve">PEVuZE5vdGU+</w:fldData></w:fldChar></w:r>'
                '<w:r><w:instrText xml:space="preserve"> ADDIN EN.CITE.DATA </w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
INS = 'w:id="{id}" w:author="Alice" w:date="2026-01-05T09:00:00Z"'
BOLD = '<w:b/>'
ITALIC = '<w:i/>'

# Each paragraph is one case. The comment after it says what must happen.
PARAGRAPHS = [
    p(r('Case studies')),                                                          # 0 heading-ish
    # 1: a citation split over three runs with different formatting -> runs cut at both edges;
    #    the first run carries a tracked formatting change, whose id the cut must not copy
    p(r('Erosion is slow (Smi', '<w:lang w:val="en-GB"/><w:rPrChange w:id="43" w:author="Alice" w:date="2026-01-05T09:00:00Z"><w:rPr/></w:rPrChange>'),
      r('th, ', BOLD), r('2020) in most holes.', ITALIC)),
    # 2: narrative -> "Smith " stays text, "(2020, p. 4)" becomes a field with suppress-author
    p(r('As Smith (2020, p. 4) showed, the buffer holds.')),
    # 3: compound -> one field, two items, prefix "see"
    p(r('Sorption varies (see Garcia & Lopez, 2021; Brown 2019) with pH.')),
    # 4: inside another author's tracked insertion -> w:del nested in her w:ins, which is split
    p(r('Flow is channelled '), f'<w:ins {INS.format(id=41)}>' + r('as reported (Brown, 2019) earlier') + '</w:ins>', r(' and stable.')),
    # 5: a deleted citation is not there; the visible one is converted
    p(r('The '), f'<w:del {INS.format(id=42)}><w:r><w:delText xml:space="preserve">old (Jones, 2018) </w:delText></w:r></w:del>', r('new view (Smith, 2020) holds.')),
    # 6: an existing Zotero citation is left alone and counted as cited
    p(r('Quality is contingent '), field(ZOTERO_EXISTING, r('(Lane, 2014)')), r('.')),
    # 7: an EndNote citation, with its nested EN.CITE.DATA field, converted whole
    p(r('Forsmark data '), field(ENDNOTE, r('(Brown, 2019)'), nested=ENDNOTE_DATA), r(' were used.')),
    # 8: a footnote reference inside the parenthesis -> refused
    p(r('Refused here (Smith, '), '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteReference w:id="2"/></w:r>', r('2020) because of the note.')),
    # 9: inside a hyperlink -> the hyperlink is split around the new field
    p(r('Online, '), '<w:hyperlink r:id="rId20" w:history="1">' + r('see (Smith, 2020) online', '<w:rStyle w:val="Hyperlink"/>') + '</w:hyperlink>', r(' too.')),
    # 10: two Jones 2020 items, but the reference list names one title -> matched to it
    p(r('Two papers fit (Jones, 2020) here.')),
    # 11: not in the library -> stays text
    p(r('Nobody has (Zzyzx, 1999) in a library.')),
    # 12: partly resolvable -> left as text entirely
    p(r('Half known (Smith, 2020; Zzyzx, 1999) stays.')),
    # 13: narrative et al., item in the group library
    p(r('Results from Öhman et al. (2014) agree.')),
    # 14: leading-year compound -> Lane suppressed, Bildtgård listed; Lane is in the group library
    p(r('This follows Lane (2014, 20; cf. Bildtgård 2010) closely.')),
    # 15: a comment beside, not inside, the citation -> converted, comment kept
    p('<w:commentRangeStart w:id="3"/>', r('Commented text'), '<w:commentRangeEnd w:id="3"/>',
      '<w:r><w:commentReference w:id="3"/></w:r>', r(' then (Brown, 2019).')),
    # 16: a year-off suggestion: Stone 2017 against Stone 2018 (only with the -wal file)
    p(r('Conventions matter (Stone et al., 2017) for quality.')),
    # 17: two Nilsson 2015 items and no entry to tell them apart -> the test chooses one
    p(r('Swelling was measured (Nilsson, 2015) twice.')),
    # 18: SKB report numbers, found in the items' Report Number: in a parenthesis with a section
    #     locator; narrative, "SKB" kept; in running text, "SKB " kept and only the number replaced
    p(r('The site model (SKB R-13-25, Section 4.2) and SKB (R-19-01) agree, as SKB R-19-01 shows.')),
]

TABLE = ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid><w:gridCol w:w="4000"/></w:tblGrid>'
         '<w:tr><w:tc><w:tcPr><w:tcW w:w="4000" w:type="dxa"/></w:tcPr>' + p(r('In a table (Garcia & Lopez, 2021).')) + '</w:tc></w:tr></w:tbl>')

REFERENCES = [
    p(r('References'), style='Heading1'),
    p(r('Bildtgård T, 2010. Taste and distinction. Journal of Taste 3, 1–10.')),
    p(r('Brown P, 2019. Groundwater flow at Forsmark. SKB R-19-01, Svensk Kärnbränslehantering AB.')),
    p(r('Garcia M, Lopez J, 2021. Radionuclide sorption on bentonite. Clays 12, 3–4.')),
    p(r('Jones A, 2020. Sulphide transport in fractured rock. Journal of Hydrology 5, 1–2.')),
    p(r('Lane C, 2014. The culture of quality. Routledge.')),
    p(r('Smith J, 2020. Buffer erosion in dilute groundwater. Applied Clay Science 185, 105–117.')),
    p(r('Uncited U, 2001. Never cited anywhere. Nowhere Press.')),
    p(r('Öhman J, Odén M, Vidstrand P, 2014. Hydrogeological modelling of SFR. SKB R-13-25.')),
]

DOCUMENT = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<w:document xmlns:w="{W}" xmlns:r="{R}">'
            '<w:body>' + ''.join(PARAGRAPHS) + TABLE + ''.join(REFERENCES)
            + '<w:bookmarkStart w:id="57" w:name="end"/><w:bookmarkEnd w:id="57"/>'
            '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')

FOOTNOTES = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<w:footnotes xmlns:w="{W}" xmlns:r="{R}">'
             '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
             '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
             '<w:footnote w:id="2"><w:p><w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteRef/></w:r>'
             + r(' A note citing (Smith, 2020) as well.') + '</w:p></w:footnote></w:footnotes>')

COMMENTS = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<w:comments xmlns:w="{W}">'
            '<w:comment w:id="3" w:author="Bob" w:date="2026-01-06T10:00:00Z" w:initials="B"><w:p>' + r('Check this.') + '</w:p></w:comment></w:comments>')

SETTINGS = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<w:settings xmlns:w="{W}">'
            '<w:zoom w:percent="100"/><w:proofState w:spelling="clean" w:grammar="clean"/>'
            '<w:defaultTabStop w:val="720"/><w:characterSpacingControl w:val="doNotCompress"/>'
            '<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>'
            '</w:settings>')

STYLES = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<w:styles xmlns:w="{W}">'
          '<w:docDefaults><w:rPrDefault><w:rPr><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
          '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>'
          '<w:style w:type="character" w:styleId="FootnoteReference"><w:name w:val="footnote reference"/><w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>'
          '</w:styles>')

CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                 '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
                 '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
                 '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
                 '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                 '</Types>')

ROOT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
             '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
             '</Relationships>')

DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
            '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
            '<Relationship Id="rId20" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.org/smith" TargetMode="External"/>'
            '</Relationships>')

CORE = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Zoterify fixture</dc:title><dc:creator>kvot ab</dc:creator></cp:coreProperties>')


def build_docx():
    path = os.path.join(OUT, 'fixture.docx')
    parts = [('[Content_Types].xml', CONTENT_TYPES), ('_rels/.rels', ROOT_RELS), ('word/document.xml', DOCUMENT),
             ('word/_rels/document.xml.rels', DOC_RELS), ('word/styles.xml', STYLES), ('word/settings.xml', SETTINGS),
             ('word/footnotes.xml', FOOTNOTES), ('word/comments.xml', COMMENTS), ('docProps/core.xml', CORE)]
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, text in parts:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode('utf-8'))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    build_databases()
    build_docx()
    print('wrote', ', '.join(sorted(os.listdir(OUT))))
