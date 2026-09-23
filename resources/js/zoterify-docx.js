/* ==========================================================================
   ZOTERIFY.HTML: EDITING THE WORD DOCUMENT IN PLACE

   Opens a .docx, reads its text the way Word shows it, and replaces plain-
   text citations with Zotero field codes. It does that as an editor would
   with Track Changes on: the original document is kept whole, and each
   replacement is a tracked deletion of the old text followed by a tracked
   insertion of the new field, by an author you name. Everything else in the
   file -- styles, comments, other people's revisions, images, headers -- is
   passed through byte for byte, and the parts that are edited are edited,
   not regenerated.

   The usual way -- accept every tracked change, strip the existing citation
   fields and write a new file -- loses the document's history. The approach
   here follows docXMLater (https://github.com/ItMeDiaTech/docXMLater, MIT):
   w:del around the old runs with w:t turned into w:delText, w:ins around the
   new ones, fresh revision ids above every id already in the package,
   w:trackRevisions in settings.xml at its place in the schema's sequence,
   and the author listed in word/people.xml.

   How the text is read (buildModel):
     - runs inside w:del and w:moveFrom are gone, as with changes accepted;
       runs inside w:ins and w:moveTo are there;
     - complex fields are followed across paragraphs with a stack, so text
       is visible only in the result part of every open field, never in an
       instruction;
     - the result of an existing Zotero citation is replaced by spaces of the
       same length, so it is not found again; Endnote and Mendeley citations
       are left readable when they are to be converted, so the parser finds
       them and the writer replaces the whole field;
     - tabs are "\t", line breaks "\n", non-breaking hyphens "-" to the
       parser; model.shown, the text as Word shows it and what a new field
       displays, keeps the non-breaking hyphen as U+2011.
   Text boxes, which live inside a paragraph's runs, are not read.

   A replacement is refused, with the reason, when it would have to cut
   through something Word would not survive or the author would not want
   lost: a footnote or comment reference, a picture, another field such as a
   hyperlink or cross-reference, a content control, moved text, or an
   existing Zotero citation.

   A citation left as text can get a Word comment saying why (addComment):
   range marks around its runs and a comment reference after them, with
   the comment in word/comments.xml. The text itself is not touched, and,
   as in Word, a comment is not a tracked change.

   Needs JSZip, DOMParser and XMLSerializer: the browser, or the page under
   headless Chrome for resources/tests/zoterify/test-docx.py.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ZFDocx = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
  const W_STRICT = 'http://purl.oclc.org/ooxml/wordprocessingml/main';
  const PKG_RELS = 'http://schemas.openxmlformats.org/package/2006/relationships';
  const CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types';
  const XML_NS = 'http://www.w3.org/XML/1998/namespace';
  const W15 = 'http://schemas.microsoft.com/office/word/2012/wordml';
  const MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006';
  const REL_BASE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/';
  const REL_PEOPLE = 'http://schemas.microsoft.com/office/2011/relationships/people';
  const CT_PEOPLE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.people+xml';
  const CT_SETTINGS = 'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml';
  const CT_COMMENTS = 'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml';
  const CSL_SCHEMA = 'https://github.com/citation-style-language/schema/raw/master/csl-citation.json';

  // Elements that hold runs and may be kept around a deletion or split.
  const SPLITTABLE = new Set(['ins', 'hyperlink', 'smartTag', 'customXml', 'dir', 'bdo']);
  const REVISION = new Set(['ins', 'del', 'moveFrom', 'moveTo']);
  const CONTAINER_REASON = {
    moveTo: 'the text was moved under Track Changes',
    sdt: 'the text is inside a content control',
    sdtContent: 'the text is inside a content control',
    fldSimple: 'the text is the result of a Word field',
  };
  // Run content that is not text and must not be deleted with a citation.
  const NON_TEXT_NAMES = {
    footnoteReference: 'a footnote reference', endnoteReference: 'an endnote reference',
    commentReference: 'a comment', annotationRef: 'a comment mark', drawing: 'a picture',
    pict: 'a picture', object: 'an embedded object', ruby: 'ruby text', footnoteRef: 'a footnote mark',
    endnoteRef: 'an endnote mark', separator: 'a note separator', continuationSeparator: 'a note separator',
    contentPart: 'ink', embedded: 'an embedded object',
  };
  const BENIGN = new Set(['rPr', 't', 'tab', 'ptab', 'br', 'cr', 'noBreakHyphen', 'softHyphen', 'sym',
    'lastRenderedPageBreak', 'fldChar', 'instrText', 'delText', 'delInstrText', 'pgNum',
    'dayShort', 'monthShort', 'yearShort', 'dayLong', 'monthLong', 'yearLong']);

  const isW = (el, local) => el && el.nodeType === 1 && el.namespaceURI === W && (!local || el.localName === local);
  const kids = (el) => Array.from(el.childNodes).filter((n) => n.nodeType === 1);

  /* ---------------------------------------------------------------------
     The package
     --------------------------------------------------------------------- */

  function dirOf(path) { const i = path.lastIndexOf('/'); return i < 0 ? '' : path.slice(0, i + 1); }

  function resolveTarget(fromPath, target) {
    if (target.startsWith('/')) return target.slice(1);
    const parts = (dirOf(fromPath) + target).split('/');
    const out = [];
    for (const p of parts) {
      if (p === '..') out.pop();
      else if (p !== '.' && p !== '') out.push(p);
    }
    return out.join('/');
  }

  function relsPathFor(partPath) {
    const d = dirOf(partPath);
    return `${d}_rels/${partPath.slice(d.length)}.rels`;
  }

  function parseXml(text, name) {
    const doc = new DOMParser().parseFromString(text, 'application/xml');
    const err = doc.getElementsByTagName('parsererror')[0];
    if (err || !doc.documentElement) throw new Error(`${name} is not well-formed XML.`);
    return doc;
  }

  async function readPart(pkg, path) {
    if (pkg.parts.has(path)) return pkg.parts.get(path).doc;
    const file = pkg.zip.file(path);
    if (!file) return null;
    const text = await file.async('string');
    const decl = /^\s*<\?xml[^>]*\?>/.exec(text);
    const doc = parseXml(text, path);
    pkg.parts.set(path, { doc, decl: decl ? decl[0].trim() : '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', dirty: false });
    return doc;
  }

  function markDirty(pkg, path) { pkg.parts.get(path).dirty = true; }

  function relationships(doc) {
    return Array.from(doc.getElementsByTagNameNS(PKG_RELS, 'Relationship')).map((r) => ({
      id: r.getAttribute('Id'), type: r.getAttribute('Type') || '', target: r.getAttribute('Target') || '',
      external: r.getAttribute('TargetMode') === 'External', el: r,
    }));
  }

  const relType = (rel, name) => rel.type === REL_BASE + name || rel.type.endsWith(`/relationships/${name}`);

  /**
   * Open a .docx.
   * @param {ArrayBuffer|Uint8Array} bytes
   * @param {Object} JSZip   the JSZip constructor
   */
  async function open(bytes, JSZip) {
    let zip;
    try {
      zip = await JSZip.loadAsync(bytes);
    } catch (e) {
      throw new Error('This is not a Word document (.docx): it is not a zip package. A .doc file must first be saved as .docx in Word.');
    }
    const pkg = { zip, parts: new Map(), mainPath: '', rels: null, relsPath: '', nextId: 1, prefix: 'w' };
    const rootRelsDoc = await readPart(pkg, '_rels/.rels');
    if (!rootRelsDoc) throw new Error('This zip file is not a Word document: it has no _rels/.rels.');
    const officeDoc = relationships(rootRelsDoc).find((r) => relType(r, 'officeDocument'));
    if (!officeDoc) throw new Error('This package has no main document part.');
    pkg.mainPath = resolveTarget('', officeDoc.target);
    const main = await readPart(pkg, pkg.mainPath);
    if (!main) throw new Error(`The main document part ${pkg.mainPath} is missing.`);
    if (main.documentElement.namespaceURI === W_STRICT) {
      throw new Error('This document is saved as "Strict Open XML", which this page does not read. In Word, save it as "Word Document (.docx)" and try again.');
    }
    if (main.documentElement.namespaceURI !== W) throw new Error('The main part is not a WordprocessingML document.');
    pkg.prefix = main.documentElement.lookupPrefix(W) || '';

    pkg.relsPath = relsPathFor(pkg.mainPath);
    pkg.relsDoc = await readPart(pkg, pkg.relsPath);
    pkg.rels = pkg.relsDoc ? relationships(pkg.relsDoc) : [];
    const partFor = (name) => {
      const r = pkg.rels.find((x) => relType(x, name) && !x.external);
      return r ? resolveTarget(pkg.mainPath, r.target) : null;
    };
    pkg.footnotesPath = partFor('footnotes');
    pkg.endnotesPath = partFor('endnotes');
    pkg.settingsPath = partFor('settings');
    pkg.commentsPath = partFor('comments');
    pkg.stylesPath = partFor('styles');
    const peopleRel = pkg.rels.find((x) => x.type === REL_PEOPLE && !x.external);
    pkg.peoplePath = peopleRel ? resolveTarget(pkg.mainPath, peopleRel.target) : null;
    for (const p of [pkg.footnotesPath, pkg.endnotesPath, pkg.settingsPath, pkg.stylesPath]) if (p) await readPart(pkg, p);

    // Revision ids must be unique: start above every w:id in every part
    // that can carry one.
    let maxId = 0;
    const idParts = [pkg.mainPath, pkg.footnotesPath, pkg.endnotesPath, pkg.commentsPath,
      ...pkg.rels.filter((r) => (relType(r, 'header') || relType(r, 'footer')) && !r.external).map((r) => resolveTarget(pkg.mainPath, r.target))];
    for (const path of idParts) {
      if (!path) continue;
      const doc = await readPart(pkg, path);
      if (!doc) continue;
      for (const node of doc.getElementsByTagNameNS('*', '*')) {
        const v = node.getAttributeNS(W, 'id');
        if (v && /^\d+$/.test(v) && Number(v) > maxId && Number(v) < 2e9) maxId = Number(v);
      }
    }
    pkg.nextId = maxId + 1;
    return pkg;
  }

  /* ---------------------------------------------------------------------
     Stories and paragraphs, in document order
     --------------------------------------------------------------------- */

  const SKIP_BLOCK = new Set(['sectPr', 'tblPr', 'tblGrid', 'trPr', 'tcPr', 'sdtPr', 'sdtEndPr', 'customXmlPr', 'pPr']);

  function collectParagraphs(rootEl) {
    const out = [];
    (function walk(el) {
      for (const child of kids(el)) {
        if (isW(child, 'p')) { out.push(child); continue; }
        if (child.namespaceURI === W && SKIP_BLOCK.has(child.localName)) continue;
        if (child.namespaceURI === MC && child.localName === 'Fallback') continue;
        walk(child);
      }
    }(rootEl));
    return out;
  }

  function stories(pkg) {
    const out = [];
    const main = pkg.parts.get(pkg.mainPath).doc;
    const body = main.getElementsByTagNameNS(W, 'body')[0];
    if (body) out.push({ story: 'body', part: pkg.mainPath, paragraphs: collectParagraphs(body) });
    for (const [path, tag, story] of [[pkg.footnotesPath, 'footnote', 'footnote'], [pkg.endnotesPath, 'endnote', 'endnote']]) {
      if (!path || !pkg.parts.has(path)) continue;
      const doc = pkg.parts.get(path).doc;
      const paragraphs = [];
      for (const note of doc.getElementsByTagNameNS(W, tag)) {
        const type = note.getAttributeNS(W, 'type');
        if (type === 'separator' || type === 'continuationSeparator' || type === 'continuationNotice') continue;
        paragraphs.push(...collectParagraphs(note));
      }
      out.push({ story, part: path, paragraphs });
    }
    return out;
  }

  /* ---------------------------------------------------------------------
     Fields
     --------------------------------------------------------------------- */

  function classifyInstr(instr) {
    const s = instr.trim();
    if (/^ADDIN\s+ZOTERO_ITEM\b/.test(s)) return 'zotero';
    if (/^ADDIN\s+ZOTERO_BIBL\b/.test(s)) return 'zotero-bibliography';
    if (/^ADDIN\s+EN\.CITE\.DATA\b/.test(s)) return 'endnote-data';
    if (/^ADDIN\s+EN\.CITE\b/.test(s)) return 'endnote';
    if (/^ADDIN\s+EN\.REFLIST\b/.test(s)) return 'endnote-bibliography';
    if (/^ADDIN\s+CSL_CITATION\b/.test(s)) return 'mendeley';
    if (/^ADDIN\s+(?:Mendeley\s+Bibliography\s+)?CSL_BIBLIOGRAPHY\b/.test(s)) return 'mendeley-bibliography';
    const word = /^([A-Za-z]+)/.exec(s);
    return word ? word[1].toUpperCase() : 'FIELD';
  }

  const CITATION_KINDS = new Set(['zotero', 'endnote', 'mendeley']);
  const KIND_LABEL = { zotero: 'Zotero', endnote: 'EndNote', mendeley: 'Mendeley' };

  /** The (surname, year, uri) of each item an existing citation field cites. */
  function citedItems(field) {
    const i = field.instr.indexOf('{');
    const j = field.instr.lastIndexOf('}');
    if (i < 0 || j < i) return [];
    try {
      const data = JSON.parse(field.instr.slice(i, j + 1));
      return (data.citationItems || []).map((ci) => {
        const d = ci.itemData || {};
        const who = (d.author || d.editor || [])[0] || {};
        const dp = d.issued && d.issued['date-parts'] && d.issued['date-parts'][0];
        return {
          surname: who.family || who.literal || '',
          year: dp && dp[0] !== undefined ? String(dp[0]) : '',
          uri: (ci.uris || ci.uri || [])[0] || '',
          title: d.title || '',
        };
      });
    } catch (e) {
      return [];
    }
  }

  /* ---------------------------------------------------------------------
     The text of a paragraph

     A model holds the paragraph's visible text and, for every run, where
     its text starts and ends in that string, what encloses it, and which
     fields are open around it. `stack` is the field stack at the start of
     the paragraph; the model leaves it as it stands at the end.
     --------------------------------------------------------------------- */

  function childLength(ch) {
    if (!isW(ch)) return 0;
    switch (ch.localName) {
      case 't': return ch.textContent.length;
      case 'tab': case 'ptab': case 'br': case 'cr': case 'noBreakHyphen': case 'sym': return 1;
      default: return 0;
    }
  }

  function childText(ch) {
    switch (ch.localName) {
      case 't': return ch.textContent;
      case 'tab': case 'ptab': return '\t';
      case 'br': case 'cr': return '\n';
      case 'noBreakHyphen': return '-';
      case 'sym': return '￼';
      default: return '';
    }
  }

  function buildModel(p, stack, options, fieldSerial) {
    const model = { p, text: '', shown: '', runs: [], fields: [] };
    const visible = () => stack.every((e) => e.phase === 'result');
    const blanked = () => stack.some((e) => e.field.protect);

    function processRun(r, containers) {
      const rec = { run: r, start: model.text.length, end: 0, containers, stack: stack.map((e) => ({ field: e.field, phase: e.phase })), fieldChars: [], hasInstr: false, nonText: [] };
      for (const ch of kids(r)) {
        if (ch.namespaceURI !== W) { rec.nonText.push('embedded content'); continue; }
        const local = ch.localName;
        if (local === 'fldChar') {
          const type = ch.getAttributeNS(W, 'fldCharType');
          if (type === 'begin') {
            const parent = stack.length ? stack[stack.length - 1].field : null;
            const field = { serial: fieldSerial.next++, instr: '', kind: null, protect: false, recode: false, parent, beginRun: r, beginModel: model, sepModel: null, endModel: null, resultStart: null, resultEnd: null };
            stack.push({ field, phase: 'instr' });
            model.fields.push(field);
            rec.fieldChars.push(field);
          } else if (type === 'separate' && stack.length) {
            const top = stack[stack.length - 1];
            classify(top.field);
            top.phase = 'result';
            top.field.sepModel = model;
            top.field.resultStart = model.text.length;
            rec.fieldChars.push(top.field);
          } else if (type === 'end' && stack.length) {
            const top = stack.pop();
            if (!top.field.kind) classify(top.field);
            top.field.endModel = model;
            top.field.endRun = r;
            if (top.field.sepModel === model) top.field.resultEnd = model.text.length;
            rec.fieldChars.push(top.field);
          }
          continue;
        }
        if (local === 'instrText') {
          rec.hasInstr = true;
          const top = stack[stack.length - 1];
          if (top && top.phase === 'instr') top.field.instr += ch.textContent;
          continue;
        }
        if (NON_TEXT_NAMES[local]) { rec.nonText.push(NON_TEXT_NAMES[local]); continue; }
        if (!BENIGN.has(local)) { rec.nonText.push(`a w:${local} element`); continue; }
        if (!visible()) continue;
        const text = childText(ch);
        model.shown += local === 'noBreakHyphen' ? '\u2011' : text;
        model.text += blanked() ? ' '.repeat(text.length) : text;
      }
      rec.end = model.text.length;
      model.runs.push(rec);
    }

    function classify(field) {
      field.kind = classifyInstr(field.instr);
      if (CITATION_KINDS.has(field.kind)) {
        const ours = options.created && options.created.has(field.beginRun);
        field.recode = !ours && !!(options.recode && options.recode[field.kind]);
        field.protect = !field.recode;
      }
    }

    (function walk(node, containers) {
      for (const ch of kids(node)) {
        if (ch.namespaceURI !== W) continue;
        const local = ch.localName;
        if (local === 'r') processRun(ch, containers);
        else if (local === 'del' || local === 'moveFrom') continue;
        else if (SPLITTABLE.has(local) || local === 'moveTo' || local === 'fldSimple' || local === 'sdt' || local === 'sdtContent') walk(ch, [...containers, ch]);
      }
    }(p, []));
    return model;
  }

  /* ---------------------------------------------------------------------
     Outline levels: which paragraphs are headings, and of what level (0 for
     Heading 1). From the paragraph's own w:outlineLvl, else its style's,
     following w:basedOn; a style named "heading N" is level N-1 even without
     one. Level 9 is body text. The parser uses this to find where a
     reference list under a heading ends.
     --------------------------------------------------------------------- */
  function styleLevels(pkg) {
    const out = new Map();
    const part = pkg.stylesPath && pkg.parts.get(pkg.stylesPath);
    if (!part) return { of: () => null, fallback: null };
    const styles = new Map();
    let defaultId = null;
    for (const st of part.doc.getElementsByTagNameNS(W, 'style')) {
      if (st.getAttributeNS(W, 'type') !== 'paragraph') continue;
      const id = st.getAttributeNS(W, 'styleId');
      const child = (name) => kids(st).find((c) => isW(c, name));
      const pPr = child('pPr');
      const lvl = pPr && kids(pPr).find((c) => isW(c, 'outlineLvl'));
      const name = child('name');
      const based = child('basedOn');
      styles.set(id, {
        outline: lvl ? Number(lvl.getAttributeNS(W, 'val')) : null,
        name: name ? name.getAttributeNS(W, 'val') : '',
        basedOn: based ? based.getAttributeNS(W, 'val') : null,
      });
      if (st.getAttributeNS(W, 'default') === '1') defaultId = id;
    }
    const of = (id, depth = 0) => {
      if (id === null || !styles.has(id) || depth > 20) return null;
      if (out.has(id)) return out.get(id);
      const st = styles.get(id);
      let level;
      if (Number.isInteger(st.outline)) level = st.outline >= 9 ? null : st.outline;
      else if (/^heading\s*([1-9])$/i.test(st.name)) level = Number(/([1-9])$/.exec(st.name)[1]) - 1;
      else level = of(st.basedOn, depth + 1);
      out.set(id, level);
      return level;
    };
    return { of, fallback: defaultId };
  }

  function paragraphLevel(p, levels) {
    const pPr = kids(p).find((c) => isW(c, 'pPr'));
    if (pPr) {
      const own = kids(pPr).find((c) => isW(c, 'outlineLvl'));
      if (own) {
        const v = Number(own.getAttributeNS(W, 'val'));
        return Number.isInteger(v) && v < 9 ? v : null;
      }
      const ps = kids(pPr).find((c) => isW(c, 'pStyle'));
      if (ps) return levels.of(ps.getAttributeNS(W, 'val'));
    }
    return levels.of(levels.fallback);
  }

  /**
   * Read every paragraph of the document.
   *
   * @param {Object} pkg
   * @param {{recode?: {endnote?: boolean, mendeley?: boolean, zotero?: boolean}}} options
   * @returns {{paras: Array<{text: string, story: string, level: number|null}>, models: Array, fields: Array}}
   */
  function analyse(pkg, options = {}) {
    const paras = [];
    const models = [];
    const fields = [];
    const fieldSerial = { next: 1 };
    const levels = styleLevels(pkg);
    for (const s of stories(pkg)) {
      const stack = [];
      for (const p of s.paragraphs) {
        const startStack = stack.map((e) => ({ field: e.field, phase: e.phase }));
        const model = buildModel(p, stack, options, fieldSerial);
        model.startStack = startStack;
        model.story = s.story;
        model.part = s.part;
        model.index = models.length;
        models.push(model);
        fields.push(...model.fields);
        paras.push({ text: model.text, story: s.story, level: s.story === 'body' ? paragraphLevel(p, levels) : null });
      }
    }
    return { paras, models, fields };
  }

  /** What the document already holds, for the page to report. */
  function inventory(pkg, analysed) {
    const count = (path, names) => {
      if (!path || !pkg.parts.has(path)) return 0;
      const doc = pkg.parts.get(path).doc;
      return names.reduce((n, name) => n + doc.getElementsByTagNameNS(W, name).length, 0);
    };
    const revisions = [pkg.mainPath, pkg.footnotesPath, pkg.endnotesPath]
      .reduce((n, path) => n + count(path, ['ins', 'del', 'moveFrom', 'moveTo', 'rPrChange', 'pPrChange']), 0);
    const byKind = {};
    for (const f of analysed.fields) byKind[f.kind] = (byKind[f.kind] || 0) + 1;
    const existing = analysed.fields.filter((f) => f.kind === 'zotero').map((f) => ({ field: f, items: citedItems(f) }));
    return {
      paragraphs: analysed.models.length,
      footnoteParagraphs: analysed.models.filter((m) => m.story !== 'body').length,
      revisions,
      trackingOn: trackingIsOn(pkg),
      fieldsByKind: byKind,
      existingZotero: existing,
    };
  }

  function trackingIsOn(pkg) {
    if (!pkg.settingsPath || !pkg.parts.has(pkg.settingsPath)) return false;
    const el = pkg.parts.get(pkg.settingsPath).doc.getElementsByTagNameNS(W, 'trackRevisions')[0];
    if (!el) return false;
    const v = el.getAttributeNS(W, 'val');
    return !(v === 'false' || v === '0' || v === 'off');
  }

  /* ---------------------------------------------------------------------
     Planning a replacement

     Which runs a span [start, end) of a paragraph's text covers, extended
     over any citation field that is to be converted, or the reason it
     cannot be replaced.
     --------------------------------------------------------------------- */

  function plan(model, start, end) {
    const include = new Set();
    let changed = true;
    while (changed) {
      changed = false;
      for (const rec of model.runs) {
        for (const e of rec.stack) {
          const f = e.field;
          if (!f.recode || include.has(f)) continue;
          const overlaps = rec.end > rec.start ? rec.start < end && rec.end > start : rec.start > start && rec.start < end;
          if (!overlaps) continue;
          if (f.beginModel !== model || f.endModel !== model || f.sepModel !== model) {
            return { error: `the ${KIND_LABEL[f.kind]} citation around it runs over more than one paragraph` };
          }
          include.add(f);
          start = Math.min(start, f.resultStart);
          end = Math.max(end, f.resultEnd);
          changed = true;
        }
      }
    }

    // A field nested in a converted one (EndNote keeps EN.CITE.DATA inside
    // the instruction of EN.CITE) goes with it.
    const within = (f) => { for (let x = f; x; x = x.parent) if (include.has(x)) return true; return false; };
    const inField = (rec) => rec.stack.some((e) => within(e.field)) || rec.fieldChars.some(within);
    const covered = [];
    model.runs.forEach((rec, i) => {
      const width = rec.end - rec.start;
      if ((width > 0 && rec.start < end && rec.end > start) || (width === 0 && rec.start > start && rec.start < end) || inField(rec)) covered.push(i);
    });
    if (!covered.length) return { error: 'its text could not be found in the document' };
    for (let k = 1; k < covered.length; k++) {
      if (covered[k] !== covered[k - 1] + 1) return { error: 'its text is interleaved with other content' };
    }
    const runs = covered.map((i) => model.runs[i]);
    for (const rec of runs) {
      for (const c of rec.containers) {
        if (!SPLITTABLE.has(c.localName)) return { error: CONTAINER_REASON[c.localName] || `the text is inside a w:${c.localName} element` };
      }
      for (const e of rec.stack) {
        if (within(e.field)) continue;
        if (e.field.protect) return { error: `it overlaps a citation that is already a ${KIND_LABEL[e.field.kind]} field` };
        return { error: `the text is the result of a ${e.field.kind} field` };
      }
      for (const f of rec.fieldChars) {
        if (!within(f)) return { error: `it contains part of ${KIND_LABEL[f.kind] ? `a ${KIND_LABEL[f.kind]} citation` : `a ${f.kind || 'Word'} field`}` };
      }
      const hard = rec.nonText.filter((d) => !inField(rec) || /reference|comment|mark/.test(d));
      if (hard.length) return { error: `the text contains ${hard[0]}` };
    }
    return { start, end, runs, include };
  }

  /* ---------------------------------------------------------------------
     Editing
     --------------------------------------------------------------------- */

  function qn(pkg, local) { return pkg.prefix ? `${pkg.prefix}:${local}` : local; }

  function el(pkg, doc, local, attrs) {
    const e = doc.createElementNS(W, qn(pkg, local));
    for (const [k, v] of Object.entries(attrs || {})) e.setAttributeNS(W, qn(pkg, k), v);
    return e;
  }

  function preserve(t) { t.setAttributeNS(XML_NS, 'xml:space', 'preserve'); }

  function revisionAttrs(pkg, rev) {
    return { id: String(pkg.nextId++), author: rev.author, date: rev.date };
  }

  function renameW(pkg, node, local) {
    const n = node.ownerDocument.createElementNS(W, qn(pkg, local));
    for (const a of Array.from(node.attributes)) n.setAttributeNS(a.namespaceURI, a.name, a.value);
    while (node.firstChild) n.appendChild(node.firstChild);
    node.parentNode.replaceChild(n, node);
    return n;
  }

  /** Split a run so that its first k visible characters stay in it. */
  function splitRun(pkg, run, k) {
    const right = run.cloneNode(false);
    const rPr = kids(run).find((c) => isW(c, 'rPr'));
    if (rPr) {
      // A tracked formatting change (w:rPrChange) in the properties carries
      // an id, which the copy must not share.
      const copy = rPr.cloneNode(true);
      for (const e of copy.getElementsByTagNameNS(W, '*')) {
        if (e.hasAttributeNS(W, 'id')) e.setAttributeNS(W, qn(pkg, 'id'), String(pkg.nextId++));
      }
      right.appendChild(copy);
    }
    let acc = 0;
    let moving = false;
    for (const ch of Array.from(run.childNodes)) {
      if (ch === rPr) continue;
      if (moving) { right.appendChild(ch); continue; }
      const len = childLength(ch);
      if (acc + len <= k) {
        acc += len;
        if (acc === k && len > 0) moving = true;
        continue;
      }
      const cut = k - acc;
      const t2 = ch.cloneNode(false);
      t2.textContent = ch.textContent.slice(cut);
      ch.textContent = ch.textContent.slice(0, cut);
      preserve(ch);
      preserve(t2);
      right.appendChild(t2);
      moving = true;
      acc = k;
    }
    run.parentNode.insertBefore(right, run.nextSibling);
  }

  /** Split every container between `node` and `p` after `node`; the top-
      level element after which new content can go at node's position. */
  function splitAfter(pkg, node, p) {
    while (node.parentNode !== p) {
      const parent = node.parentNode;
      let after = false;
      for (let s = node.nextSibling; s; s = s.nextSibling) {
        if (s.nodeType === 1 || (s.nodeType === 3 && s.data.trim())) { after = true; break; }
      }
      if (after) {
        const clone = parent.cloneNode(false);
        const props = kids(parent).find((c) => c.namespaceURI === W && /Pr$/.test(c.localName));
        if (props) clone.appendChild(props.cloneNode(true));
        if (REVISION.has(parent.localName)) clone.setAttributeNS(W, qn(pkg, 'id'), String(pkg.nextId++));
        while (node.nextSibling) clone.appendChild(node.nextSibling);
        parent.parentNode.insertBefore(clone, parent.nextSibling);
      }
      node = parent;
    }
    return node;
  }

  function isEmptyContainer(c) {
    return !kids(c).some((k) => !(k.namespaceURI === W && /Pr$/.test(k.localName)));
  }

  /** The run properties the new field's text takes: the first replaced
      run's, without its own revision marks. */
  function resultRunProps(runs) {
    const src = runs.find((r) => r.end > r.start) || runs[0];
    const rPr = kids(src.run).find((c) => isW(c, 'rPr'));
    if (!rPr) return null;
    const copy = rPr.cloneNode(true);
    for (const c of kids(copy)) {
      if (c.namespaceURI === W && (c.localName === 'rPrChange' || REVISION.has(c.localName))) copy.removeChild(c);
      else if (isW(c, 'rStyle') && src.containers.some((x) => x.localName === 'hyperlink')) copy.removeChild(c);
    }
    return copy;
  }

  function randomId(n = 8) {
    const abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    const bytes = new Uint8Array(n);
    (typeof crypto !== 'undefined' && crypto.getRandomValues ? crypto.getRandomValues(bytes) : bytes.forEach((_, i) => { bytes[i] = Math.floor(Math.random() * 256); }));
    return Array.from(bytes, (b) => abc[b % abc.length]).join('');
  }

  /**
   * The Zotero field instruction for one group of references.
   * @param {Array<{ref: Object, item: Object}>} members
   * @param {string} text   the text the field will show
   */
  function citationInstruction(members, text) {
    const seen = new Set();
    const citationItems = [];
    for (const { ref, item } of members) {
      if (seen.has(item.itemId)) continue;
      seen.add(item.itemId);
      const ci = { id: item.itemId, uris: [item.uri], itemData: item.csl };
      if (ref.locator) { ci.locator = ref.locator; ci.label = ref.locatorLabel || 'page'; }
      if (ref.prefix) ci.prefix = ref.prefix;
      if (ref.suffix) ci.suffix = ref.suffix;
      if (ref.suppressAuthor) ci['suppress-author'] = true;
      citationItems.push(ci);
    }
    const json = {
      citationID: randomId(),
      properties: { formattedCitation: text, plainCitation: text, noteIndex: 0 },
      citationItems,
      schema: CSL_SCHEMA,
    };
    return ` ADDIN ZOTERO_ITEM CSL_CITATION ${JSON.stringify(json)} `;
  }

  /**
   * Replace [start, end) of a paragraph with a Zotero field.
   *
   * @returns {{ok: true, deleted: string, inserted: string} | {ok: false, reason: string}}
   */
  function replaceSpan(pkg, model, start, end, members, rev, options) {
    let pl = plan(model, start, end);
    if (pl.error) return { ok: false, reason: pl.error };

    // Cut the runs at the span's edges, the right edge first so the left
    // cut still counts from the run's own start, then read again.
    const cuts = [];
    for (const at of [pl.end, pl.start]) {
      const rec = pl.runs.find((r) => r.start < at && at < r.end);
      if (!rec) continue;
      if (rec.fieldChars.length || rec.hasInstr) return { ok: false, reason: 'its edge falls inside a field character run' };
      cuts.push([rec, at]);
    }
    for (const [rec, at] of cuts) splitRun(pkg, rec.run, at - rec.start);
    if (cuts.length) {
      model = rebuild(model, options);
      pl = plan(model, pl.start, pl.end);
      if (pl.error) return { ok: false, reason: pl.error };
    }

    const doc = model.p.ownerDocument;
    const shown = model.shown.slice(pl.start, pl.end);
    const display = shown.replace(/[\t\n]/g, ' ').replace(/￼/g, '');
    const rPr = resultRunProps(pl.runs);

    const last = pl.runs[pl.runs.length - 1].run;
    const marker = doc.createComment('zoterify');
    last.parentNode.insertBefore(marker, last.nextSibling);

    // The old text: a tracked deletion, or gone.
    const groups = [];
    for (const rec of pl.runs) {
      const g = groups[groups.length - 1];
      const prev = g && g[g.length - 1];
      let adjacent = false;
      if (prev && prev.parentNode === rec.run.parentNode) {
        adjacent = true;
        for (let s = prev.nextSibling; s && s !== rec.run; s = s.nextSibling) {
          if (s.nodeType === 1 || (s.nodeType === 3 && s.data.trim())) { adjacent = false; break; }
        }
      }
      if (adjacent) g.push(rec.run); else groups.push([rec.run]);
    }
    const touched = new Set(pl.runs.flatMap((r) => r.containers));
    for (const g of groups) {
      if (rev) {
        const del = el(pkg, doc, 'del', revisionAttrs(pkg, rev));
        g[0].parentNode.insertBefore(del, g[0]);
        for (const run of g) {
          del.appendChild(run);
          for (const t of Array.from(run.getElementsByTagNameNS(W, 't'))) renameW(pkg, t, 'delText');
          for (const t of Array.from(run.getElementsByTagNameNS(W, 'instrText'))) renameW(pkg, t, 'delInstrText');
        }
      } else {
        for (const run of g) run.parentNode.removeChild(run);
      }
    }

    // The new field: begin, instruction, separate, text, end -- as Zotero
    // writes it, with the formatting on the text run only.
    const runs = [];
    const fld = (type) => { const r = el(pkg, doc, 'r'); r.appendChild(el(pkg, doc, 'fldChar', { fldCharType: type })); return r; };
    runs.push(fld('begin'));
    if (options.created) options.created.add(runs[0]);
    const ir = el(pkg, doc, 'r');
    const it = el(pkg, doc, 'instrText');
    preserve(it);
    it.textContent = citationInstruction(members, display);
    ir.appendChild(it);
    runs.push(ir);
    runs.push(fld('separate'));
    const tr = el(pkg, doc, 'r');
    if (rPr) tr.appendChild(rPr);
    const t = el(pkg, doc, 't');
    preserve(t);
    t.textContent = display;
    tr.appendChild(t);
    runs.push(tr);
    runs.push(fld('end'));

    const anchor = splitAfter(pkg, marker, model.p);
    const where = anchor.nextSibling;
    if (rev) {
      const ins = el(pkg, doc, 'ins', revisionAttrs(pkg, rev));
      for (const r of runs) ins.appendChild(r);
      model.p.insertBefore(ins, where);
    } else {
      for (const r of runs) model.p.insertBefore(r, where);
    }
    marker.parentNode.removeChild(marker);
    if (!rev) {
      for (const c of touched) if (c.parentNode && isEmptyContainer(c)) c.parentNode.removeChild(c);
    }
    markDirty(pkg, model.part);
    return { ok: true, deleted: shown, inserted: display };
  }

  function rebuild(model, options) {
    const stack = model.startStack.map((e) => ({ field: e.field, phase: e.phase }));
    const fresh = buildModel(model.p, stack, options, { next: 1e9 });
    return Object.assign(fresh, { startStack: model.startStack, story: model.story, part: model.part, index: model.index });
  }

  /* ---------------------------------------------------------------------
     settings.xml, people.xml, relationships, content types
     --------------------------------------------------------------------- */

  // CT_Settings children that come before w:trackRevisions (ECMA-376 Part 1,
  // 17.15.1.78). It goes in front of the first child not in this list.
  const SETTINGS_BEFORE_TRACK = new Set(['writeProtection', 'view', 'zoom', 'removePersonalInformation',
    'removeDateAndTime', 'doNotDisplayPageBoundaries', 'displayBackgroundShape', 'printPostScriptOverText',
    'printFractionalCharacterWidth', 'printFormsData', 'embedTrueTypeFonts', 'embedSystemFonts',
    'saveSubsetFonts', 'saveFormsData', 'mirrorMargins', 'alignBordersAndEdges', 'bordersDoNotSurroundHeader',
    'bordersDoNotSurroundFooter', 'gutterAtTop', 'hideSpellingErrors', 'hideGrammaticalErrors',
    'activeWritingStyle', 'proofState', 'formsDesign', 'attachedTemplate', 'linkStyles',
    'stylePaneFormatFilter', 'stylePaneSortMethod', 'documentType', 'mailMerge', 'revisionView']);

  async function setTracking(pkg, on) {
    if (!pkg.settingsPath) {
      if (!on) return;
      pkg.settingsPath = resolveTarget(pkg.mainPath, 'settings.xml');
      const doc = parseXml(`<w:settings xmlns:w="${W}"/>`, 'settings.xml');
      pkg.parts.set(pkg.settingsPath, { doc, decl: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', dirty: true });
      addRelationship(pkg, `${REL_BASE}settings`, 'settings.xml');
      await addOverride(pkg, `/${pkg.settingsPath}`, CT_SETTINGS);
    }
    const doc = pkg.parts.get(pkg.settingsPath).doc;
    const settings = doc.documentElement;
    const pfx = settings.lookupPrefix(W) || '';
    const existing = settings.getElementsByTagNameNS(W, 'trackRevisions')[0];
    if (!on) {
      if (existing) { existing.parentNode.removeChild(existing); markDirty(pkg, pkg.settingsPath); }
      return;
    }
    if (existing) {
      if (existing.hasAttributeNS(W, 'val')) existing.removeAttributeNS(W, 'val');
    } else {
      const track = doc.createElementNS(W, pfx ? `${pfx}:trackRevisions` : 'trackRevisions');
      const before = kids(settings).find((c) => !(c.namespaceURI === W && SETTINGS_BEFORE_TRACK.has(c.localName)));
      settings.insertBefore(track, before || null);
    }
    markDirty(pkg, pkg.settingsPath);
  }

  function addRelationship(pkg, type, target) {
    if (!pkg.relsDoc) {
      pkg.relsDoc = parseXml(`<Relationships xmlns="${PKG_RELS}"/>`, pkg.relsPath);
      pkg.parts.set(pkg.relsPath, { doc: pkg.relsDoc, decl: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', dirty: true });
    }
    const ids = new Set(relationships(pkg.relsDoc).map((r) => r.id));
    let n = ids.size + 1;
    while (ids.has(`rId${n}`)) n++;
    const r = pkg.relsDoc.createElementNS(PKG_RELS, 'Relationship');
    r.setAttribute('Id', `rId${n}`);
    r.setAttribute('Type', type);
    r.setAttribute('Target', target);
    pkg.relsDoc.documentElement.appendChild(r);
    markDirty(pkg, pkg.relsPath);
    pkg.rels = relationships(pkg.relsDoc);
  }

  async function addOverride(pkg, partName, contentType) {
    const doc = await readPart(pkg, '[Content_Types].xml');
    const has = Array.from(doc.getElementsByTagNameNS(CT_NS, 'Override')).some((o) => o.getAttribute('PartName') === partName);
    if (has) return;
    const o = doc.createElementNS(CT_NS, 'Override');
    o.setAttribute('PartName', partName);
    o.setAttribute('ContentType', contentType);
    doc.documentElement.appendChild(o);
    markDirty(pkg, '[Content_Types].xml');
  }

  /** List the revision author in word/people.xml, as Word itself does. */
  async function addPerson(pkg, author) {
    if (!pkg.peoplePath) {
      let path = resolveTarget(pkg.mainPath, 'people.xml');
      for (let n = 2; pkg.zip.file(path) || pkg.parts.has(path); n++) path = resolveTarget(pkg.mainPath, `people${n}.xml`);
      pkg.peoplePath = path;
      const doc = parseXml(`<w15:people xmlns:mc="${MC}" xmlns:w15="${W15}" mc:Ignorable="w15"/>`, path);
      pkg.parts.set(path, { doc, decl: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', dirty: true });
      addRelationship(pkg, REL_PEOPLE, path.slice(dirOf(pkg.mainPath).length));
      await addOverride(pkg, `/${path}`, CT_PEOPLE);
    }
    const doc = await readPart(pkg, pkg.peoplePath);
    const people = doc.documentElement;
    const exists = Array.from(doc.getElementsByTagNameNS(W15, 'person')).some((p) => p.getAttributeNS(W15, 'author') === author);
    if (exists) return;
    const pfx = people.lookupPrefix(W15) || 'w15';
    const person = doc.createElementNS(W15, `${pfx}:person`);
    person.setAttributeNS(W15, `${pfx}:author`, author);
    const info = doc.createElementNS(W15, `${pfx}:presenceInfo`);
    info.setAttributeNS(W15, `${pfx}:providerId`, 'None');
    info.setAttributeNS(W15, `${pfx}:userId`, author);
    person.appendChild(info);
    people.appendChild(person);
    markDirty(pkg, pkg.peoplePath);
  }

  /* ---------------------------------------------------------------------
     Comments
     --------------------------------------------------------------------- */

  /** An element in the W namespace of a part other than the one the
      package's prefix was read from. */
  function wIn(doc, local, attrs) {
    const pfx = doc.documentElement.lookupPrefix(W) || 'w';
    const e = doc.createElementNS(W, `${pfx}:${local}`);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttributeNS(W, `${pfx}:${k}`, v);
    return e;
  }

  /** word/comments.xml, made with its relationship and content type when
      the document has no comments yet. */
  async function commentsPart(pkg) {
    if (!pkg.commentsPath) {
      let path = resolveTarget(pkg.mainPath, 'comments.xml');
      for (let n = 2; pkg.zip.file(path) || pkg.parts.has(path); n++) path = resolveTarget(pkg.mainPath, `comments${n}.xml`);
      pkg.commentsPath = path;
      const doc = parseXml(`<w:comments xmlns:w="${W}"/>`, path);
      pkg.parts.set(path, { doc, decl: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', dirty: true });
      addRelationship(pkg, `${REL_BASE}comments`, path.slice(dirOf(pkg.mainPath).length));
      await addOverride(pkg, `/${path}`, CT_COMMENTS);
    }
    return readPart(pkg, pkg.commentsPath);
  }

  /** The comment itself, one paragraph per line; its id. */
  async function newComment(pkg, lines, who) {
    const doc = await commentsPart(pkg);
    const id = String(pkg.nextId++);
    const initials = who.author.split(/\s+/).filter(Boolean).map((w) => Array.from(w)[0]).join('').toUpperCase().slice(0, 9);
    const c = wIn(doc, 'comment', { id, author: who.author, date: who.date, initials: initials || 'Z' });
    lines.forEach((line, k) => {
      const p = wIn(doc, 'p');
      if (k === 0) {
        const mark = wIn(doc, 'r');
        mark.appendChild(wIn(doc, 'annotationRef'));
        p.appendChild(mark);
      }
      const r = wIn(doc, 'r');
      const t = wIn(doc, 't');
      preserve(t);
      t.textContent = line;
      r.appendChild(t);
      p.appendChild(r);
      c.appendChild(p);
    });
    doc.documentElement.appendChild(c);
    markDirty(pkg, pkg.commentsPath);
    return id;
  }

  const coveredRuns = (model, start, end) => model.runs.filter((r) => r.end > r.start && r.start < end && r.end > start);

  /**
   * A comment on [start, end) of a paragraph. The runs are cut at the
   * edges so the range covers the citation and no more; a citation in the
   * result of a field (an EndNote citation left as it was) gets the range
   * around the whole field, which its program may rewrite. The comment
   * reference goes after the range, outside any hyperlink or insertion it
   * ends in.
   */
  async function addComment(pkg, model, start, end, lines, who, options) {
    let runs = coveredRuns(model, start, end);
    if (!runs.length) return false;
    let cut = false;
    for (const at of [end, start]) {
      const rec = runs.find((r) => r.start < at && at < r.end);
      if (!rec || rec.fieldChars.length || rec.hasInstr) continue;
      splitRun(pkg, rec.run, at - rec.start);
      cut = true;
    }
    if (cut) {
      model = rebuild(model, options);
      runs = coveredRuns(model, start, end);
    }
    let first = runs[0].run;
    let last = runs[runs.length - 1].run;
    const outer = (rec) => (rec.stack.length ? rec.stack[0].field : null);
    const f0 = outer(runs[0]);
    if (f0 && f0.beginRun && model.p.contains(f0.beginRun)) first = f0.beginRun;
    const f1 = outer(runs[runs.length - 1]);
    if (f1 && f1.endRun && model.p.contains(f1.endRun)) last = f1.endRun;

    markAround(pkg, model.p, first, last, await newComment(pkg, lines, who));
    markDirty(pkg, model.part);
    return true;
  }

  /** Range marks from before `first` to after `last`, and the comment
      reference after them at the level of the paragraph. */
  function markAround(pkg, p, first, last, id) {
    const doc = p.ownerDocument;
    first.parentNode.insertBefore(el(pkg, doc, 'commentRangeStart', { id }), first);
    const rangeEnd = el(pkg, doc, 'commentRangeEnd', { id });
    last.parentNode.insertBefore(rangeEnd, last.nextSibling);
    let top = rangeEnd;
    while (top.parentNode !== p) top = top.parentNode;
    const ref = el(pkg, doc, 'r');
    ref.appendChild(el(pkg, doc, 'commentReference', { id }));
    p.insertBefore(ref, top.nextSibling);
  }

  /**
   * A comment on a citation in a footnote or endnote goes on the note's
   * mark in the body text instead, its first line saying which citation it
   * is about. Comments belong to the main document: the Open XML SDK does
   * not resolve one anchored inside a note, and that is not worth risking
   * on a document Word must open.
   */
  async function addNoteComment(pkg, analysed, model, text, lines, who) {
    let note = model.p;
    while (note && !(isW(note, 'footnote') || isW(note, 'endnote'))) note = note.parentNode;
    if (!note) return false;
    const noteId = note.getAttributeNS(W, 'id');
    const main = pkg.parts.get(pkg.mainPath).doc;
    const mark = Array.from(main.getElementsByTagNameNS(W, `${note.localName}Reference`)).find((r) => r.getAttributeNS(W, 'id') === noteId);
    const run = mark && mark.parentNode;
    const body = run && analysed.models.find((m) => m.story === 'body' && m.p.contains(run));
    if (!body) return false;
    const where = note.localName === 'footnote' ? 'footnote' : 'endnote';
    markAround(pkg, body.p, run, run, await newComment(pkg, [`In the ${where} marked here, at “${text}”:`, ...lines], who));
    markDirty(pkg, pkg.mainPath);
    return true;
  }

  /** A comment at the start of the document: on the first body paragraph
      with text that is not inside a field, before its first run. */
  async function addOpeningComment(pkg, analysed, lines, who) {
    const model = analysed.models.find((m) => m.story === 'body' && m.text.trim() && !m.startStack.length) || analysed.models.find((m) => m.story === 'body');
    if (!model) return false;
    const p = model.p;
    const doc = p.ownerDocument;
    const id = await newComment(pkg, lines, who);
    const at = kids(p).find((c) => !isW(c, 'pPr')) || null;
    const ref = el(pkg, doc, 'r');
    ref.appendChild(el(pkg, doc, 'commentReference', { id }));
    for (const node of [el(pkg, doc, 'commentRangeStart', { id }), el(pkg, doc, 'commentRangeEnd', { id }), ref]) p.insertBefore(node, at);
    markDirty(pkg, model.part);
    return true;
  }

  /* ---------------------------------------------------------------------
     Writing the citations
     --------------------------------------------------------------------- */

  const xmlDate = (d) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');

  /**
   * Write Zotero fields for resolved citations into an opened package.
   *
   * @param {Object} pkg        from open()
   * @param {Object} analysed   from analyse(pkg, options) -- must be the
   *                            reading the citations were found in
   * @param {Array<{para: number, start: number, end: number, refs: Array, items: Array, problem: ?string}>} groups
   *        groups as zoterify-parse.js finds them, each with the library item
   *        every reference resolves to (null when it is unresolved)
   * @param {{track: boolean, keepTracking: boolean, author: string, recode: Object, date?: Date,
   *          commentText?: function(Object, string, boolean): ?Array<string>,
   *          summaryText?: function({written: Array, skipped: Array}): ?Array<string>}} options
   *        commentText, when given, is asked for the lines of a comment on
   *        each group left as text -- with the reason, and whether it was the
   *        writer that refused it -- and summaryText for a comment at the
   *        start of the document
   * @returns {Promise<{written: Array, skipped: Array<{group, reason, commented}>, summarised: boolean}>}
   */
  async function writeCitations(pkg, analysed, groups, options) {
    const who = { author: options.author || 'Zoterify', date: xmlDate(options.date || new Date()) };
    const rev = options.track ? who : null;
    const jobs = groups.map((g) => ({
      group: g, model: g.para, start: g.start, end: g.end,
      reason: g.problem || (g.items.some((it) => !it) ? 'not every reference in it is resolved yet' : null),
    }));
    // Later positions first, so earlier offsets in the paragraph hold.
    jobs.sort((a, b) => (a.model - b.model) || (b.start - a.start) || (b.end - a.end));
    const written = [];
    const skipped = [];
    const opts = Object.assign({}, options, { created: new WeakSet() });
    let comments = 0;
    for (const job of jobs) {
      let reason = job.reason;
      if (!reason) {
        const members = job.group.refs.map((ref, i) => ({ ref, item: job.group.items[i] }));
        const res = replaceSpan(pkg, rebuild(analysed.models[job.model], opts), job.start, job.end, members, rev, opts);
        if (res.ok) { written.push({ group: job.group, deleted: res.deleted, inserted: res.inserted }); continue; }
        reason = res.reason;
      }
      const entry = { group: job.group, reason, commented: false };
      const lines = options.commentText ? options.commentText(job.group, reason, !job.reason) : null;
      if (lines && lines.length) {
        const model = analysed.models[job.model];
        const from = Number.isInteger(job.group.authorStart) ? Math.min(job.group.authorStart, job.start) : job.start;
        entry.commented = model.story === 'body'
          ? await addComment(pkg, rebuild(model, opts), from, job.end, lines, who, opts)
          : await addNoteComment(pkg, analysed, model, model.shown.slice(from, job.end), lines, who);
        if (entry.commented) comments++;
      }
      skipped.push(entry);
    }
    skipped.sort((a, b) => (a.group.para - b.group.para) || (a.group.start - b.group.start));
    const result = { written, skipped, summarised: false };
    const summary = options.summaryText ? options.summaryText(result) : null;
    if (summary && summary.length) result.summarised = await addOpeningComment(pkg, analysed, summary, who);
    if ((written.length && rev) || comments || result.summarised) await addPerson(pkg, who.author);
    await setTracking(pkg, !!options.keepTracking);
    return result;
  }

  /** The edited package as bytes. Parts that were not touched are copied. */
  async function save(pkg) {
    const serializer = new XMLSerializer();
    for (const [path, part] of pkg.parts) {
      if (!part.dirty) continue;
      const xml = serializer.serializeToString(part.doc).replace(/^\s*<\?xml[^>]*\?>\s*/, '');
      // No folder entries: an OPC package has none, and the original had none.
      pkg.zip.file(path, `${part.decl}\r\n${xml}`, { createFolders: false });
    }
    return pkg.zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE', compressionOptions: { level: 6 } });
  }

  return {
    open, analyse, inventory, writeCitations, save, citedItems, classifyInstr, trackingIsOn,
    // for the tests
    plan, buildModel, stories,
  };
}));
