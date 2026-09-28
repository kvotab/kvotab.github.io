/* ==========================================================================
   SMUI.HTML: A REPORT AS A WORD DOCUMENT (.docx)

   Save > Save Report as Word writes the report as JMP's journal would: the
   title, then every open outline as a heading, its tables as Word tables,
   its graphs as pictures (drawn in the light theme), its notes and
   messages as paragraphs, and the Python code (when the report shows it)
   in a monospace style. Closed outlines are left out, as in print. The file is Office Open XML
   (WordprocessingML) zipped with JSZip, which the page loads already.

     const blob = await SM.docx.report(report);
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});

  const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"';
  const EMU = 9525;                          // per CSS pixel (96 dpi)
  const TEXT_W = 9360 * 635;                 // 6.5 in of text width, in EMU (twips x 635)

  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    // characters XML 1.0 cannot hold
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g, '');

  const run = (text, { bold = false, italic = false, color = null, mono = false, size = null } = {}) => {
    const pr = [bold ? '<w:b/>' : '', italic ? '<w:i/>' : '', color ? `<w:color w:val="${color}"/>` : '', mono ? '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>' : '', size ? `<w:sz w:val="${size}"/>` : ''].join('');
    return `<w:r>${pr ? `<w:rPr>${pr}</w:rPr>` : ''}<w:t xml:space="preserve">${esc(text)}</w:t></w:r>`;
  };
  const para = (content, { style = null, align = null, keepNext = false } = {}) => {
    const pr = [style ? `<w:pStyle w:val="${style}"/>` : '', keepNext ? '<w:keepNext/>' : '', align ? `<w:jc w:val="${align}"/>` : ''].join('');
    return `<w:p>${pr ? `<w:pPr>${pr}</w:pPr>` : ''}${content}</w:p>`;
  };

  const visible = (e) => { const cs = getComputedStyle(e); return cs.display !== 'none' && cs.visibility !== 'hidden'; };
  const SKIP = 'button, input, select, textarea, .kvot-info-slot, [data-noexport], .sm-ob-toggle, .sm-ob-menu, script, style';

  /* The rows of a report table as text, as the page shows them. */
  function tableXml(tbl) {
    const rows = [...tbl.querySelectorAll(':scope > thead > tr, :scope > tbody > tr, :scope > tr, :scope > tfoot > tr')].filter(visible);
    if (!rows.length) return '';
    const head = tbl.tHead ? [...tbl.tHead.rows] : [];
    const width = Math.max(...rows.map((r) => [...r.cells].length));
    const out = [];
    for (const tr of rows) {
      const isHead = head.includes(tr);
      const cells = [...tr.cells];
      const tcs = cells.map((c) => {
        const left = c.classList.contains('sm-l') || (tbl.classList.contains('sm-kv') && c.cellIndex === 0);
        const sig = c.classList.contains('p-sig');
        const span = c.colSpan > 1 ? `<w:gridSpan w:val="${c.colSpan}"/>` : '';
        const shd = isHead ? '<w:shd w:val="clear" w:color="auto" w:fill="F5EEE7"/>' : '';
        return `<w:tc><w:tcPr>${span}${shd}</w:tcPr>${para(run(c.textContent.trim(), { bold: isHead || sig, color: sig ? 'C8322B' : null }), { style: 'SmCell', align: left ? 'left' : 'right' })}</w:tc>`;
      });
      for (let k = cells.reduce((a, c) => a + (c.colSpan || 1), 0); k < width; k++) tcs.push(`<w:tc>${para('', { style: 'SmCell' })}</w:tc>`);
      out.push(`<w:tr>${isHead ? '<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>' : '<w:trPr><w:cantSplit/></w:trPr>'}${tcs.join('')}</w:tr>`);
    }
    const cap = tbl.caption && tbl.caption.textContent.trim();
    return (cap ? para(run(cap), { style: 'Caption', keepNext: true }) : '')
      + `<w:tbl><w:tblPr><w:tblStyle w:val="SmTable"/><w:tblW w:w="0" w:type="auto"/><w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/></w:tblPr>${out.join('')}</w:tbl>`
      + para('', { style: 'SmSpace' });
  }

  function pictureXml(img, n) {
    let w = img.w * EMU, h = img.h * EMU;
    if (w > TEXT_W) { h = Math.round(h * TEXT_W / w); w = TEXT_W; }
    return para(`<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="${w}" cy="${h}"/><wp:docPr id="${n}" name="Picture ${n}" descr="${esc(img.alt || 'graph')}"/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="${n}" name="image${n}.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rIdImg${n}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${w}" cy="${h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>`, { style: 'SmPicture' });
  }

  /* An inline SVG (a tree, a network, a word cloud) as a PNG: a copy with
     its computed paint written in (SM.report.paintedSvg, light colours in
     the dark theme), drawn on a canvas. */
  async function svgImage(svg) {
    const r = svg.getBoundingClientRect();
    if (!(r.width > 2 && r.height > 2)) return null;
    const copy = SM.report.paintedSvg(svg);
    const src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(copy))}`;
    const im = new Image();
    await new Promise((res, rej) => { im.onload = res; im.onerror = rej; im.src = src; });
    const c = document.createElement('canvas');
    c.width = Math.round(r.width * 2); c.height = Math.round(r.height * 2);
    const g = c.getContext('2d');
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, c.width, c.height);
    g.drawImage(im, 0, 0, c.width, c.height);
    return { data: c.toDataURL('image/png'), w: Math.round(r.width), h: Math.round(r.height), alt: svg.getAttribute('aria-label') || 'diagram' };
  }

  const b64bytes = (dataUrl) => {
    const s = atob(dataUrl.slice(dataUrl.indexOf(',') + 1));
    const out = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  };

  /* The report's open parts, in order, as WordprocessingML. */
  async function bodyOf(report, images) {
    const out = [];
    const walk = async (node, level) => {
      for (const e of node.children) {
        if (e.matches(SKIP) || !visible(e)) continue;
        if (e.classList.contains('sm-ob')) {
          const h = e.querySelector(':scope > .sm-ob-head h2, :scope > .sm-ob-head h3, :scope > .sm-ob-head h4');
          if (h) out.push(para(run(h.textContent.trim()), { style: `Heading${Math.min(6, level + 1)}`, keepNext: true }));
          const body = e.querySelector(':scope > .sm-ob-body');
          if (body && !e.classList.contains('is-closed')) await walk(body, level + 1);
        } else if (e.matches('table.sm-rt, table.sm-kv')) {
          out.push(tableXml(e));
        } else if (e.classList.contains('sm-plot')) {
          const p = e._plot;
          const img = p && images.plot ? await images.plot(p) : null;
          if (img) { images.list.push(img); out.push(pictureXml(img, images.list.length)); }
          else out.push(para(run('(graph not drawn)', { italic: true }), { style: 'SmNote' }));
        } else if (e.tagName === 'svg' || e.tagName === 'SVG') {
          let img = null;
          try { img = await svgImage(e); } catch (err) { img = null; }
          if (img) { images.list.push(img); out.push(pictureXml(img, images.list.length)); }
        } else if (e.matches('details.sm-code')) {
          const pre = e.querySelector('pre');
          // the Python, when the report shows it (the Python code button) or the block is open
          if (pre && !e.closest('.sm-ob-error') && (report.spec.options.showCode || e.open)) {
            out.push(para(run('Python code', { bold: true }), { style: 'SmNote', keepNext: true }));
            for (const line of pre.textContent.replace(/\n$/, '').split('\n')) out.push(para(run(line, { mono: true }), { style: 'SmCode' }));
          }
        } else if (e.matches('.sm-ob-note, p.sm-ob-note')) {
          out.push(para(run(e.textContent.trim()), { style: 'SmNote' }));
        } else if (e.matches('.sm-ob-warn, .sm-ob-error')) {
          out.push(para(run(e.textContent.trim()), { style: 'SmWarn' }));
        } else if (e.children.length) {
          await walk(e, level);
        } else {
          const t = e.textContent.trim();
          if (t) out.push(para(run(t)));
        }
      }
    };
    await walk(report.content, 0);
    return out.join('');
  }

  const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Verdana" w:hAnsi="Verdana" w:cs="Verdana" w:eastAsia="Verdana"/><w:sz w:val="18"/><w:szCs w:val="18"/><w:color w:val="352921"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="60" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="80"/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="60"/><w:ind w:left="0"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="21"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="160" w:after="40"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="19"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="120" w:after="40"/><w:outlineLvl w:val="3"/></w:pPr><w:rPr><w:b/><w:i/><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading5"><w:name w:val="heading 5"/><w:basedOn w:val="Heading4"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:outlineLvl w:val="4"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading6"><w:name w:val="heading 6"/><w:basedOn w:val="Heading4"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:outlineLvl w:val="5"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="80" w:after="20"/></w:pPr><w:rPr><w:b/><w:color w:val="6B5D50"/><w:sz w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="SmNote"><w:name w:val="Report Note"/><w:basedOn w:val="Normal"/><w:rPr><w:color w:val="6B5D50"/><w:sz w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="SmWarn"><w:name w:val="Report Message"/><w:basedOn w:val="Normal"/><w:pPr><w:pBdr><w:left w:val="single" w:sz="18" w:space="6" w:color="F3B87B"/></w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="FDF4E9"/></w:pPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="SmCode"><w:name w:val="Report Code"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:shd w:val="clear" w:color="auto" w:fill="F7F2EC"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:sz w:val="16"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="SmCell"><w:name w:val="Report Cell"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="SmSpace"><w:name w:val="Report Space"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="80"/></w:pPr><w:rPr><w:sz w:val="8"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="SmPicture"><w:name w:val="Report Picture"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="60" w:after="120"/></w:pPr></w:style>
<w:style w:type="table" w:customStyle="1" w:styleId="SmTable"><w:name w:val="Report Table"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="E0D7CE"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="E0D7CE"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="E0D7CE"/></w:tblBorders><w:tblCellMar><w:top w:w="20" w:type="dxa"/><w:left w:w="90" w:type="dxa"/><w:bottom w:w="20" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>`;

  /* The report as a .docx Blob. images.plot(p) gives a graph's PNG. */
  async function report(rep, { plotImage } = {}) {
    if (typeof JSZip === 'undefined') throw new Error('the zip library did not load: check the network');
    const images = { list: [], plot: plotImage || null };
    const body = await bodyOf(rep, images);
    const today = new Date().toISOString().slice(0, 10);
    const meta = `${rep.table ? `Table: ${rep.table.name}. ` : ''}Made with the User Interface for statsmodels (kvotab.se/smui.html), statsmodels ${SM.engine.versions ? SM.engine.versions.statsmodels : ''}, ${today}.`;
    const doc = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document ${NS}><w:body>${para(run(rep.title), { style: 'Title' })}${para(run(meta), { style: 'SmNote' })}${body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr></w:body></w:document>`;
    const rels = ['<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
      ...images.list.map((_, i) => `<Relationship Id="rIdImg${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image${i + 1}.png"/>`)];
    const zip = new JSZip();
    zip.file('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>');
    zip.file('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>');
    zip.file('docProps/core.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>${esc(rep.title)}</dc:title><dc:creator>User Interface for statsmodels</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">${new Date().toISOString().replace(/\.\d+Z$/, 'Z')}</dcterms:created></cp:coreProperties>`);
    zip.file('word/document.xml', doc);
    zip.file('word/styles.xml', STYLES);
    zip.file('word/_rels/document.xml.rels', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels.join('')}</Relationships>`);
    images.list.forEach((im, i) => zip.file(`word/media/image${i + 1}.png`, b64bytes(im.data)));
    return zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', compression: 'DEFLATE' });
  }

  SM.docx = Object.freeze({ report });
}(typeof self !== 'undefined' ? self : this));
