/* ==========================================================================
   arsred-export.js — årsredovisningen som Word och PDF

   Båda exporterna läses ur den färdiga iXBRL-handlingen, inte ur någon egen
   modell vid sidan av. Det är avsiktligt: handlingen är det som lämnas in, och
   en Word-fil eller en PDF byggd av något annat skulle kunna glida isär från
   den utan att någon märker det. Står texten i exporten står den i det som
   skickas.

   Därför fungerar exporten också på en handling som någon annan skrivit — en
   iXBRL-fil från ett bokslutsprogram, inläst i steg B1, blir läsbar på samma
   villkor.

   Ingenting hämtas utifrån. Zip-skrivaren och PDF-skrivaren nedan finns för
   att sidan ska fungera lika bra utan nät som med, och för att en
   årsredovisning på några kilobyte inte är värd ett bibliotek.
   ========================================================================== */

const KVOT_ARSRED_EXPORT = (() => {
  'use strict';

  // ── Teckenbredder ─────────────────────────────────────────────────────────

  /*
    PDF:ens tre standardtypsnitt behöver inte bäddas in, men deras bredder
    måste vara kända här för att belopp ska kunna högerställas och stycken
    radbrytas. Tabellerna är glyfbredder i 1/1000 em för koderna 0-255 i
    WinAnsiEncoding, hämtade ur Adobes AFM-filer för Times.
  */
  const WIDTHS = (() => {
    const packed = {
      roman: '0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,250,333,408,500,500,833,778,180,333,333,500,564,250,333,250,278,500,500,500,500,500,500,500,500,500,500,278,278,564,564,564,444,921,722,667,667,722,611,556,722,722,333,389,722,611,889,722,722,556,722,667,556,611,722,722,944,722,722,611,333,278,333,469,500,333,444,500,444,500,444,333,500,500,278,278,500,278,778,500,500,500,500,333,389,278,500,500,722,500,500,444,480,200,480,541,250,250,0,333,500,444,1000,500,500,333,1000,556,333,889,0,611,0,0,333,333,444,444,350,500,1000,333,980,389,333,722,0,444,722,250,333,500,500,500,500,200,500,333,760,276,500,564,250,760,333,400,564,250,250,333,500,453,250,333,250,310,500,750,750,750,444,722,722,722,722,722,722,889,667,611,611,611,611,333,333,333,333,722,722,722,722,722,722,722,564,722,722,722,722,722,722,556,500,444,444,444,444,444,444,667,444,444,444,444,444,278,278,278,278,500,500,500,500,500,500,500,564,500,500,500,500,500,500,500,500',
      bold: '0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,250,333,555,500,500,1000,833,278,333,333,500,570,250,333,250,278,500,500,500,500,500,500,500,500,500,500,333,333,570,570,570,500,930,722,667,722,722,667,611,778,778,389,500,778,667,944,722,778,611,778,722,556,667,722,722,1000,722,722,667,333,278,333,581,500,333,500,556,444,556,444,333,500,556,278,333,556,278,833,556,500,556,556,444,389,333,556,500,722,500,500,444,394,220,394,520,250,250,0,333,500,500,1000,500,500,333,1000,556,333,1000,0,667,0,0,333,333,500,500,350,500,1000,333,1000,389,333,722,0,444,722,250,333,500,500,500,500,220,500,333,747,300,500,570,250,747,333,400,570,250,250,333,556,540,250,333,250,330,500,750,750,750,500,722,722,722,722,722,722,1000,722,667,667,667,667,389,389,389,389,722,722,778,778,778,778,778,570,778,722,722,722,722,722,611,556,500,500,500,500,500,500,722,444,444,444,444,444,278,278,278,278,500,556,500,500,500,500,500,570,500,556,556,556,556,500,556,500',
      italic: '0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,250,333,420,500,500,833,778,214,333,333,500,675,250,333,250,278,500,500,500,500,500,500,500,500,500,500,333,333,675,675,675,500,920,611,611,667,722,611,611,722,722,333,444,667,556,833,667,722,611,722,611,500,556,722,611,833,611,556,556,389,278,389,422,500,333,500,500,444,500,444,278,500,500,278,278,444,278,722,500,500,500,500,389,389,278,500,444,667,444,444,389,400,275,400,541,250,250,0,333,500,556,889,500,500,333,1000,500,333,944,0,556,0,0,333,333,556,556,350,500,889,333,980,389,333,667,0,389,556,250,389,500,500,500,500,275,500,333,760,276,500,675,250,760,333,400,675,250,250,333,500,523,250,333,250,310,500,750,750,750,500,611,611,611,611,611,611,889,667,611,611,611,611,333,333,333,333,722,667,722,722,722,722,722,675,722,722,722,722,722,556,611,500,500,500,500,500,500,500,667,444,444,444,444,444,278,278,278,278,500,500,500,500,500,500,500,675,500,500,500,500,500,444,500,444',
    };
    const out = {};
    for (const [name, text] of Object.entries(packed)) out[name] = text.split(',').map(Number);
    return out;
  })();

  /*
    WinAnsi är cp1252, som är latin-1 utom i 0x80-0x9F där Microsoft lade
    typografiska tecken. Tankstrecket och de böjda citattecknen bor där, och de
    förekommer i en årsredovisning. Fem koder i intervallet är odefinierade, så
    kartan skrivs kod för kod i stället för som en sträng.
  */
  const CP1252_HIGH = new Map([
    ['\u20ac', 0x80], ['\u201a', 0x82], ['\u0192', 0x83], ['\u201e', 0x84], ['\u2026', 0x85], ['\u2020', 0x86],
    ['\u2021', 0x87], ['\u02c6', 0x88], ['\u2030', 0x89], ['\u0160', 0x8a], ['\u2039', 0x8b], ['\u0152', 0x8c],
    ['\u017d', 0x8e], ['\u2018', 0x91], ['\u2019', 0x92], ['\u201c', 0x93], ['\u201d', 0x94], ['\u2022', 0x95],
    ['\u2013', 0x96], ['\u2014', 0x97], ['\u02dc', 0x98], ['\u2122', 0x99], ['\u0161', 0x9a], ['\u203a', 0x9b],
    ['\u0153', 0x9c], ['\u017e', 0x9e], ['\u0178', 0x9f],
  ]);

  /**
   * Text som WinAnsi-byte.
   *
   * Tecken utanför cp1252 blir frågetecken hellre än att tyst försvinna — ett
   * synligt frågetecken går att upptäcka i korrekturet.
   *
   * @param {string} text
   * @returns {number[]}
   */
  function winAnsi(text) {
    const bytes = [];
    for (const character of String(text ?? '')) {
      const code = character.codePointAt(0);
      if (code < 0x80 || (code >= 0xa0 && code <= 0xff)) { bytes.push(code); continue; }
      bytes.push(CP1252_HIGH.get(character) ?? 0x3f);
    }
    return bytes;
  }

  /**
   * Textens bredd i punkter.
   *
   * @param {string} text
   * @param {string} font - roman, bold eller italic
   * @param {number} size
   * @returns {number}
   */
  function textWidth(text, font, size) {
    const table = WIDTHS[font] || WIDTHS.roman;
    let total = 0;
    for (const byte of winAnsi(text)) total += table[byte] || 0;
    return total * size / 1000;
  }

  // ── Handlingen som block ──────────────────────────────────────────────────

  const NS_XHTML = 'http://www.w3.org/1999/xhtml';

  /**
   * Texten i ett element, med <br/> som enda radbrytning.
   *
   * Radbrytningarna i källan är indrag, inte innehåll: XHTML låter dem falla
   * ihop till mellanslag, och gör inte den här läsaren detsamma bryts varje
   * mening där filen råkar radbrytas. Bara ett verkligt <br/> bryter raden.
   *
   * @param {Element} node
   * @returns {string}
   */
  function blockText(node) {
    const parts = [];
    (function walk(current) {
      for (const child of current.childNodes) {
        if (child.nodeType === 3) parts.push(String(child.nodeValue).replace(/\s+/g, ' '));
        else if (child.nodeType === 1) {
          if (child.localName === 'br') parts.push('\n');
          else walk(child);
        }
      }
    })(node);
    /* Indraget i uppställningen är hårda mellanslag; de hör till tabellens
       kolumn, inte till texten, och läggs tillbaka som djup längre ned. */
    return parts.join('').replace(/ +/g, ' ').replace(/ *\n */g, '\n').trim();
  }

  /** Hur djupt indragen en post är, räknat på de hårda mellanslagen. */
  function indentOf(node) {
    const raw = (node.textContent || '');
    const leading = /^\u00a0+/.exec(raw);
    return leading ? Math.round(leading[0].length / 3) : 0;
  }

  /**
   * Dela upp en iXBRL-handling i de block en Word-fil eller en PDF består av.
   *
   * Går igenom body i dokumentordning och tar rubriker, stycken, tabeller och
   * underskriftsblock. ix:header hoppas över: den bär kontexter och enheter,
   * inte text någon ska läsa.
   *
   * @param {string} xhtml
   * @returns {{title: string, blocks: Object[]}}
   * @throws {Error} om filen inte går att tolka som XHTML
   */
  function blocksFromIxbrl(xhtml) {
    const doc = new DOMParser().parseFromString(xhtml, 'application/xhtml+xml');
    const failure = doc.getElementsByTagName('parsererror')[0];
    if (failure) {
      throw new Error((failure.textContent || 'okänt XML-fel').replace(/\s+/g, ' ').trim());
    }

    const body = doc.getElementsByTagNameNS(NS_XHTML, 'body')[0] || doc.documentElement;
    const titleNode = doc.getElementsByTagNameNS(NS_XHTML, 'title')[0];
    const blocks = [];

    for (const node of body.children) {
      if (node.localName === 'header' || node.namespaceURI !== NS_XHTML) continue;
      const name = node.localName;

      if (/^h[1-6]$/.test(name)) {
        const text = blockText(node);
        if (text) blocks.push({ type: 'heading', level: Number(name[1]), text });
      } else if (name === 'p') {
        const text = blockText(node);
        if (!text) continue;
        /* En inledande rubrik står fet först i stycket och fortsätter på samma
           rad — så ser en svensk förvaltningsberättelse ut, och det är den
           enda blandningen av stilar i hela handlingen. */
        const runin = node.firstElementChild
          && node.firstElementChild.classList.contains('rubrik-in')
          ? blockText(node.firstElementChild) : '';
        blocks.push(runin
          ? { type: 'para', runin, text: text.slice(runin.length).trim() }
          : { type: 'para', text });
      } else if (name === 'table') {
        blocks.push(tableBlock(node));
      } else if (name === 'div' && node.classList.contains('titelsida')) {
        /* Titelsidan är centrerad och har egna storlekar; den skulle annars
           falla bort helt, eftersom den varken är rubrik, stycke eller
           tabell. */
        blocks.push({
          type: 'title',
          rader: [...node.children].map(child => ({
            text: blockText(child),
            klass: child.className || '',
          })).filter(rad => rad.text),
        });
      } else if (name === 'div' && node.classList.contains('underskrift')) {
        blocks.push({
          type: 'signature',
          namn: blockText(node.querySelector('.namn') || document.createElement('i'))
            .replace(/\n/g, ' '),
          roll: blockText(node.querySelector('.roll') || document.createElement('i'))
            .replace(/\n/g, ' '),
          extra: [...node.querySelectorAll('p')].slice(2).map(blockText).filter(Boolean),
        });
      }
    }

    return { title: titleNode ? blockText(titleNode) : 'Årsredovisning', blocks };
  }

  function tableBlock(table) {
    const cellsOf = (row) => [...row.children].map(cell => ({
      text: blockText(cell),
      right: cell.classList.contains('belopp'),
      header: cell.localName === 'th',
      span: Number(cell.getAttribute('colspan') || 1),
      indent: indentOf(cell),
    }));
    const head = [...table.querySelectorAll('thead tr')].map(cellsOf);
    const body = [...table.querySelectorAll('tbody tr')].map(cellsOf);
    const columns = Math.max(1, ...head.concat(body).map(row =>
      row.reduce((sum, cell) => sum + cell.span, 0)));
    return { type: 'table', head, rows: body, columns };
  }

  // ── Zip, utan komprimering ────────────────────────────────────────────────

  /*
    En docx är en zip. Posterna lagras okomprimerade, vilket zip-formatet
    tillåter och Word läser utan invändning: en årsredovisning är några
    kilobyte, och en deflate-implementation här skulle vara mer kod än hela
    resten av filen.
  */
  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let i = 0; i < 256; i++) {
      let c = i;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      table[i] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  }

  /**
   * Bygg en zip av namngivna filer.
   *
   * @param {Array<{name: string, data: Uint8Array}>} entries
   * @returns {Uint8Array}
   */
  function zipStore(entries) {
    const chunks = [];
    const central = [];
    let offset = 0;

    const u16 = (value) => [value & 0xff, (value >>> 8) & 0xff];
    const u32 = (value) => [value & 0xff, (value >>> 8) & 0xff,
                            (value >>> 16) & 0xff, (value >>> 24) & 0xff];

    for (const entry of entries) {
      const name = winAnsi(entry.name);
      const crc = crc32(entry.data);
      const size = entry.data.length;
      /* Tidsstämpeln sätts till en fast tidpunkt så att samma innehåll ger
         samma byte. En fil som ändrar sig av sig själv går inte att jämföra. */
      const header = [...u32(0x04034b50), ...u16(20), ...u16(0), ...u16(0),
                      ...u16(0), ...u16(0x21), ...u32(crc), ...u32(size), ...u32(size),
                      ...u16(name.length), ...u16(0), ...name];
      chunks.push(Uint8Array.from(header), entry.data);
      central.push([...u32(0x02014b50), ...u16(20), ...u16(20), ...u16(0), ...u16(0),
                    ...u16(0), ...u16(0x21), ...u32(crc), ...u32(size), ...u32(size),
                    ...u16(name.length), ...u16(0), ...u16(0), ...u16(0), ...u16(0),
                    ...u32(0), ...u32(offset), ...name]);
      offset += header.length + size;
    }

    const directory = central.flat();
    const end = [...u32(0x06054b50), ...u16(0), ...u16(0),
                 ...u16(entries.length), ...u16(entries.length),
                 ...u32(directory.length), ...u32(offset), ...u16(0)];
    chunks.push(Uint8Array.from(directory), Uint8Array.from(end));

    const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const out = new Uint8Array(total);
    let at = 0;
    for (const chunk of chunks) { out.set(chunk, at); at += chunk.length; }
    return out;
  }

  const utf8 = (text) => new TextEncoder().encode(text);

  // ── Word ──────────────────────────────────────────────────────────────────

  const xml = (value) => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  /** Text med radbrytningar som Word förstår. */
  function runs(text, opts = {}) {
    const props = '<w:rPr>'
      + (opts.bold ? '<w:b/>' : '')
      + (opts.italic ? '<w:i/>' : '')
      + (opts.size ? `<w:sz w:val="${opts.size * 2}"/>` : '')
      + '</w:rPr>';
    return String(text ?? '').split('\n').map((line, index) =>
      `<w:r>${props}${index ? '<w:br/>' : ''}`
      + `<w:t xml:space="preserve">${xml(line)}</w:t></w:r>`).join('');
  }

  function docxBody(blocks) {
    const out = [];
    for (const block of blocks) {
      if (block.type === 'title') {
        for (const rad of block.rader) {
          const stor = /titel/.test(rad.klass) ? 22 : /\bnamn\b/.test(rad.klass) ? 16 : 11;
          out.push('<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="80"/></w:pPr>'
            + `${runs(rad.text, { size: stor, bold: /titel|\bnamn\b/.test(rad.klass) })}</w:p>`);
        }
        out.push('<w:p/>');
      } else if (block.type === 'heading') {
        out.push(`<w:p><w:pPr><w:pStyle w:val="Heading${Math.min(3, block.level)}"/></w:pPr>`
          + `${runs(block.text)}</w:p>`);
      } else if (block.type === 'para') {
        out.push('<w:p>'
          + (block.runin ? runs(block.runin + ' ', { bold: true }) : '')
          + runs(block.text) + '</w:p>');
      } else if (block.type === 'signature') {
        out.push('<w:p><w:pPr><w:spacing w:before="480"/><w:pBdr>'
          + '<w:top w:val="single" w:sz="6" w:space="2" w:color="000000"/></w:pBdr></w:pPr>'
          + `${runs(block.namn)}</w:p>`);
        if (block.roll) out.push(`<w:p>${runs(block.roll, { italic: true })}</w:p>`);
        for (const extra of block.extra || []) out.push(`<w:p>${runs(extra)}</w:p>`);
      } else if (block.type === 'table') {
        out.push(docxTable(block));
      }
    }
    return out.join('');
  }

  function docxTable(block) {
    const cell = (item, width) => {
      const indent = item.indent
        ? `<w:ind w:left="${item.indent * 200}"/>` : '';
      return `<w:tc><w:tcPr><w:tcW w:w="${width}" w:type="dxa"/>`
        + `${item.span > 1 ? `<w:gridSpan w:val="${item.span}"/>` : ''}`
        + '</w:tcPr>'
        + `<w:p><w:pPr>${item.right ? '<w:jc w:val="right"/>' : indent}</w:pPr>`
        + `${runs(item.text, { bold: item.header })}</w:p></w:tc>`;
    };
    /* Etikettkolumnen tar resten; beloppkolumnerna är lika breda. */
    const total = 9060;
    const amount = block.columns > 1 ? 1700 : 0;
    const first = total - amount * (block.columns - 1);
    const width = (index, span) => (index === 0 ? first : amount) + amount * (span - 1);

    const row = (cells) => '<w:tr>' + cells.map((item, index) =>
      cell(item, width(index, item.span))).join('') + '</w:tr>';

    return '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>'
      + '<w:tblBorders><w:insideH w:val="single" w:sz="2" w:color="CCCCCC"/></w:tblBorders>'
      + '</w:tblPr>'
      + block.head.map(row).join('') + block.rows.map(row).join('')
      + '</w:tbl><w:p/>';
  }

  const DOCX_STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults><w:rPrDefault><w:rPr>
    <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>
    <w:sz w:val="22"/><w:lang w:val="sv-SE"/>
  </w:rPr></w:rPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/><w:pPr><w:spacing w:after="120"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/>
    <w:spacing w:before="240" w:after="120"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="34"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/>
    <w:spacing w:before="280" w:after="120"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="2"/>
    <w:spacing w:before="200" w:after="80"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="23"/></w:rPr></w:style>
</w:styles>`;

  /**
   * Årsredovisningen som en .docx.
   *
   * @param {{title: string, blocks: Object[]}} doc - från blocksFromIxbrl
   * @returns {Blob}
   */
  function buildDocx(doc) {
    const document = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>${docxBody(doc.blocks)}
    <w:sectPr><w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1418"/></w:sectPr>
  </w:body>
</w:document>`;

    const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>`;

    const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="word/document.xml"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>
</Relationships>`;

    const docRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="styles.xml"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"/>
</Relationships>`;

    const zip = zipStore([
      { name: '[Content_Types].xml', data: utf8(contentTypes) },
      { name: '_rels/.rels', data: utf8(rels) },
      { name: 'word/document.xml', data: utf8(document) },
      { name: 'word/styles.xml', data: utf8(DOCX_STYLES) },
      { name: 'word/_rels/document.xml.rels', data: utf8(docRels) },
    ]);
    return new Blob([zip], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
  }


  // ── PDF ───────────────────────────────────────────────────────────────────

  /*
    Sidan är A4 och typsnitten är tre av PDF:ens fjorton inbyggda, som inte
    behöver bäddas in. Det är därför den här filen kan skriva en PDF utan
    bibliotek och utan att ta med en fontfil: allt som krävs är att veta hur
    breda tecknen är, och det står i WIDTHS längst upp.
  */
  const PAGE = Object.freeze({
    width: 595.28, height: 841.89,
    left: 56, right: 56, top: 64, bottom: 64,
  });
  const SIZE = Object.freeze({ h1: 19, h2: 14, h3: 11.5, body: 10.5, table: 9.5 });
  const LEADING = 1.35;
  const FONT_ID = Object.freeze({ roman: '/F1', bold: '/F2', italic: '/F3' });

  /** En PDF-sträng: WinAnsi-byte med de tre tecken formatet självt använder undantagna. */
  function pdfString(text) {
    let out = '(';
    for (const byte of winAnsi(text)) {
      const character = String.fromCharCode(byte);
      out += (character === '(' || character === ')' || character === '\\') ? '\\' + character
        : character;
    }
    return out + ')';
  }

  /**
   * Bryt text till rader som ryms inom en bredd.
   *
   * Ord som ensamma är bredare än raden — en lång URL, ett sammansatt ord —
   * får stå över kanten hellre än att brytas mitt i. Det syns, och det är
   * bättre än att tyst tappa tecken.
   *
   * @param {string} text
   * @param {number} width
   * @param {string} font
   * @param {number} size
   * @returns {string[]}
   */
  function wrap(text, width, font, size) {
    const lines = [];
    for (const paragraph of String(text ?? '').split('\n')) {
      let line = '';
      for (const word of paragraph.split(/\s+/)) {
        if (!word) continue;
        const candidate = line ? line + ' ' + word : word;
        if (line && textWidth(candidate, font, size) > width) { lines.push(line); line = word; }
        else line = candidate;
      }
      lines.push(line);
    }
    return lines;
  }

  /** En sida under uppbyggnad, med sitt eget innehållsflöde. */
  function newPage() { return { ops: [] }; }

  /**
   * Årsredovisningen som en PDF.
   *
   * @param {{title: string, blocks: Object[]}} doc - från blocksFromIxbrl
   * @returns {Blob}
   */
  function buildPdf(doc) {
    const contentWidth = PAGE.width - PAGE.left - PAGE.right;
    const pages = [newPage()];
    let page = pages[0];
    let y = PAGE.height - PAGE.top;

    const place = (needed) => {
      if (y - needed >= PAGE.bottom) return;
      page = newPage();
      pages.push(page);
      y = PAGE.height - PAGE.top;
    };

    const write = (text, x, font, size) => {
      page.ops.push(`BT ${FONT_ID[font]} ${size} Tf 1 0 0 1 ${x.toFixed(2)} `
        + `${y.toFixed(2)} Tm ${pdfString(text)} Tj ET`);
    };

    /* dy räknas uppåt, som allt annat i PDF. En linje under en textrad måste
       alltså ligga på ett negativt dy från baslinjen — ett positivt värde
       hamnar mitt i texten, vilket det gjorde tills korrekturet visade en
       överstruken datumrad. */
    const rule = (x1, x2, thickness = 0.5, dy = 3) => {
      const at = (y + dy).toFixed(2);
      page.ops.push(`${thickness} w ${x1.toFixed(2)} ${at} m ${x2.toFixed(2)} ${at} l S`);
    };

    const paragraph = (text, font, size, opts = {}) => {
      const indent = opts.indent || 0;
      /* Den feta inledningen tar sin plats på första raden, och resten av
         stycket flyter vidare efter den. */
      const runin = opts.runin || '';
      const runinWidth = runin ? textWidth(runin + ' ', 'bold', size) : 0;
      const lines = [];
      if (runin) {
        const first = wrap(text, contentWidth - indent - runinWidth, font, size);
        lines.push({ text: first[0] || '', x: indent + runinWidth, runin: true });
        const rest = first.slice(1).join(' ');
        for (const line of wrap(rest, contentWidth - indent, font, size)) {
          if (line) lines.push({ text: line, x: indent });
        }
      } else {
        for (const line of wrap(text, contentWidth - indent, font, size)) {
          lines.push({ text: line, x: indent });
        }
      }
      for (const line of lines) {
        place(size * LEADING);
        y -= size * LEADING;
        if (line.runin) write(runin, PAGE.left + indent, 'bold', size);
        if (line.text) write(line.text, PAGE.left + line.x, font, size);
      }
      y -= opts.after ?? size * 0.45;
    };

    for (const block of doc.blocks) {
      if (block.type === 'title') {
        y -= 40;
        for (const rad of block.rader) {
          const size = /titel/.test(rad.klass) ? 22 : /\bnamn\b/.test(rad.klass) ? 15 : SIZE.body;
          const font = /titel|\bnamn\b/.test(rad.klass) ? 'bold' : 'roman';
          place(size * LEADING);
          y -= size * LEADING;
          write(rad.text, PAGE.left + (contentWidth - textWidth(rad.text, font, size)) / 2,
                font, size);
          if (/orgnr/.test(rad.klass)) y -= 26;
        }
        y -= 34;
      } else if (block.type === 'heading') {
        const size = block.level === 1 ? SIZE.h1 : block.level === 2 ? SIZE.h2 : SIZE.h3;
        /* En rubrik längst ned på en sida hör ihop med det som följer. */
        place(size * LEADING * 3);
        y -= size * (block.level === 1 ? 0.7 : 1.1);
        paragraph(block.text, 'bold', size, { after: size * 0.5 });
      } else if (block.type === 'para') {
        paragraph(block.text, 'roman', SIZE.body, { runin: block.runin });
      } else if (block.type === 'signature') {
        place(70);
        y -= 34;
        rule(PAGE.left, PAGE.left + 200, 0.6);
        y -= SIZE.body * LEADING;
        write(block.namn, PAGE.left, 'roman', SIZE.body);
        if (block.roll) {
          y -= SIZE.body * LEADING;
          write(block.roll, PAGE.left, 'italic', SIZE.body);
        }
        for (const extra of block.extra || []) {
          y -= SIZE.body * LEADING;
          write(extra, PAGE.left, 'roman', SIZE.body);
        }
        y -= 6;
      } else if (block.type === 'table') {
        drawTable(block);
      }
    }

    function drawTable(block) {
      const size = SIZE.table;
      const amountColumns = Math.max(0, block.columns - 1);
      /* Beloppkolumnerna får en fast bredd som rymmer nio siffror med
         tusenavskiljare; etiketten tar resten. */
      const amountWidth = amountColumns
        ? Math.min(105, (contentWidth - 150) / amountColumns) : 0;
      const labelWidth = contentWidth - amountWidth * amountColumns;
      /* Kolumn 0 är etiketten och tar labelWidth; beloppkolumnerna börjar
         där den slutar. Att räkna index i stället för index-1 här sköt sista
         kolumnen en hel kolumnbredd utanför sidan, vilket syntes först när
         flerårsöversiktens jämförelseår försvann i högermarginalen. */
      const columnX = (index) => index === 0 ? PAGE.left
        : PAGE.left + labelWidth + amountWidth * (index - 1);

      const drawRow = (cells, bold) => {
        const heights = cells.map((cell, index) => {
          if (cell.right) return cell.text.split('\n').length;
          const available = (cell.span > 1 ? contentWidth : labelWidth) - cell.indent * 11 - 6;
          return wrap(cell.text, available, bold || cell.header ? 'bold' : 'roman', size).length;
        });
        const rows = Math.max(1, ...heights);
        place(size * LEADING * rows + 2);
        for (let line = 0; line < rows; line++) {
          y -= size * LEADING;
          cells.forEach((cell, index) => {
            const font = bold || cell.header ? 'bold' : 'roman';
            if (cell.right) {
              /* Beloppkolumnernas rubriker bär två datum med en radbrytning
                 emellan; varje rad ställs för sig mot kolumnens högerkant. */
              const parts = cell.text.split('\n');
              if (!parts[line]) return;
              const x = columnX(index) + amountWidth - 4 - textWidth(parts[line], font, size);
              write(parts[line], x, font, size);
              return;
            }
            const available = (cell.span > 1 ? contentWidth : labelWidth) - cell.indent * 11 - 6;
            const wrapped = wrap(cell.text, available, font, size);
            if (wrapped[line]) write(wrapped[line], columnX(index) + cell.indent * 11, font, size);
          });
        }
        return rows;
      };

      y -= 4;
      for (const cells of block.head) {
        drawRow(cells, true);
        rule(PAGE.left, PAGE.left + contentWidth, 0.7, -3.5);
      }
      for (const cells of block.rows) drawRow(cells, false);
      y -= 10;
    }

    return new Blob([assemblePdf(pages, doc.title)], { type: 'application/pdf' });
  }

  /**
   * Sätt ihop objekten till en fil, med korsreferenstabellen som pekar rätt.
   *
   * Byggs som en sträng där varje tecken är en byte, så att teckenindex och
   * byteoffset är samma tal. Ett UTF-8-steg på slutet skulle flytta varje
   * offset efter första tecknet över 127 och göra tabellen fel.
   *
   * @param {Object[]} pages
   * @param {string} title
   * @returns {Uint8Array}
   */
  function assemblePdf(pages, title) {
    const objects = [];
    const add = (body) => { objects.push(body); return objects.length; };

    const catalog = add('');            // 1, fylls i när sidträdet är känt
    const pageTree = add('');           // 2
    const fonts = ['Times-Roman', 'Times-Bold', 'Times-Italic'].map(name =>
      add(`<< /Type /Font /Subtype /Type1 /BaseFont /${name} /Encoding /WinAnsiEncoding >>`));

    const pageIds = [];
    for (const item of pages) {
      const stream = item.ops.join('\n');
      const contents = add(`<< /Length ${winAnsi(stream).length} >>\nstream\n${stream}\nendstream`);
      pageIds.push(add(`<< /Type /Page /Parent ${pageTree} 0 R `
        + `/MediaBox [0 0 ${PAGE.width} ${PAGE.height}] `
        + `/Resources << /Font << /F1 ${fonts[0]} 0 R /F2 ${fonts[1]} 0 R `
        + `/F3 ${fonts[2]} 0 R >> >> /Contents ${contents} 0 R >>`));
    }

    objects[catalog - 1] = `<< /Type /Catalog /Pages ${pageTree} 0 R >>`;
    objects[pageTree - 1] = `<< /Type /Pages /Count ${pageIds.length} `
      + `/Kids [${pageIds.map(id => id + ' 0 R').join(' ')}] >>`;
    const info = add(`<< /Title ${pdfString(title)} /Producer ${pdfString('kvot ab')} >>`);

    let out = '%PDF-1.4\n%\xe2\xe3\xcf\xd3\n';
    const offsets = [];
    objects.forEach((body, index) => {
      offsets.push(out.length);
      out += `${index + 1} 0 obj\n${body}\nendobj\n`;
    });

    const xref = out.length;
    out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
    for (const offset of offsets) out += String(offset).padStart(10, '0') + ' 00000 n \n';
    out += `trailer\n<< /Size ${objects.length + 1} /Root ${catalog} 0 R /Info ${info} 0 R >>\n`
      + `startxref\n${xref}\n%%EOF\n`;

    const bytes = new Uint8Array(out.length);
    for (let i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 0xff;
    return bytes;
  }


  // ── Att lämna ifrån sig filen ─────────────────────────────────────────────

  /** Spara en blob under ett namn. */
  function saveAs(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    /* Att återkalla direkt kapplöper med nedladdningen i vissa webbläsare. */
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  /**
   * Tolka en iXBRL-handling och lämna den som Word eller PDF.
   *
   * Samma väg för handlingen sidan just skrivit och för en som lästs in i
   * steg B1, eftersom båda är samma sorts fil.
   *
   * @param {string} xhtml
   * @param {'docx'|'pdf'} kind
   * @param {string} basename - utan filändelse
   * @returns {boolean} om det gick
   */
  function exportDocument(xhtml, kind, basename) {
    let doc;
    try {
      doc = blocksFromIxbrl(xhtml);
    } catch (error) {
      reportFailure('arsred-export.parse', error, {
        userMessage: 'Handlingen gick inte att läsa som XHTML, så den kan inte exporteras.',
      });
      return false;
    }
    if (!doc.blocks.length) {
      showFailureBanner('Handlingen innehåller ingen text att exportera.', 'error');
      return false;
    }
    const name = (basename || 'arsredovisning').replace(/\.[^.]+$/, '');
    saveAs(kind === 'pdf' ? buildPdf(doc) : buildDocx(doc), `${name}.${kind}`);
    return true;
  }

  return { winAnsi, textWidth, wrap, blocksFromIxbrl, zipStore, crc32,
           buildDocx, buildPdf, saveAs, exportDocument, WIDTHS };
})();

if (typeof module === 'object' && module.exports) module.exports = KVOT_ARSRED_EXPORT;
