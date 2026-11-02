/* ==========================================================================
   4g. XML FILES (.xml)

   An XML file opens as an HDF5 file of its own, written in memory as a JSON
   file is (rb-json.js, which has the pieces both share):

       the root element         a group at the top, named by its tag
       an element               a group named by its tag; its attributes as
                                attributes named @name, its text beside its
                                elements as the dataset #text
       an element of text       a dataset of its text: numbers when the text
                                is numbers -- one, or a list of them between
                                spaces, | or ; -- else a string; its
                                attributes on the dataset
       elements of one tag      tag[1], tag[2], ... in their order; or, when
                                each is a record -- attributes, and elements
                                of text alone each once -- a table: a group
                                named by the tag with a dataset for each
                                attribute and element, its values over all
                                of them in order

   A comma is no separator between numbers, as 2,5 is two and a half where
   a decimal comma is written. Comments, processing instructions and the
   document type are left out. Entities and CDATA are read as the browser's
   XML parser reads them, which fetches nothing from outside the file and
   refuses an entity that grows too big.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/* A number as XML files write one: Fortran's 1.5D+03 and 5. too; not 007, which is a code. */
const XML_NUMBER = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?$/;
const XML_NOT_NUMBER = /^[+-]?0\d/;
const XML_SPECIAL = /^[+-]?(?:inf|infinity|nan)$/i;

/**
 * Whether bytes handed over are an XML file: by its name, or by being no
 * HDF5 and starting as XML does (rb-json.js docSniff).
 *
 * @param {string} fileName
 * @param {ArrayBuffer|null} buffer - null to decide by the name alone
 * @returns {boolean}
 */
function isXmlFile(fileName, buffer) {
  if (/\.xml$/i.test(String(fileName || ''))) return true;
  return docSniff(buffer) === 'xml';
}

/** A token's number, or undefined when it is not one. */
function xmlNumber(token) {
  if (XML_NUMBER.test(token) && !XML_NOT_NUMBER.test(token)) return Number(token.replace(/[dD]/, 'e'));
  if (XML_SPECIAL.test(token)) return /nan/i.test(token) ? NaN : token.startsWith('-') ? -Infinity : Infinity;
  return undefined;
}

/** Text that is numbers -- one, or a list between spaces, | or ; -- as doubles; else null. */
function xmlNumbers(text) {
  const tokens = text.split(/[\s|;]+/).filter(Boolean);
  if (!tokens.length || tokens.length > 1e8) return null;
  const out = new Float64Array(tokens.length);
  for (let k = 0; k < tokens.length; k++) {
    const v = xmlNumber(tokens[k]);
    if (v === undefined) return null;
    out[k] = v;
  }
  return out;
}

/** An element's own text, beside its elements: its text and CDATA, trimmed and joined. */
function xmlOwnText(el) {
  const parts = [];
  for (let c = el.firstChild; c; c = c.nextSibling) {
    if (c.nodeType === 3 || c.nodeType === 4) {
      const t = c.data.trim();
      if (t) parts.push(t);
    }
  }
  return parts.join(' ');
}

/** An element's attributes, named @name, for the node it is written as. */
function xmlAttributes(el) {
  const out = {};
  for (const a of el.attributes) out[`@${a.name}`] = a.value;
  return out;
}

/** Whether an element is a record: no text of its own, and elements of text alone, each once and without attributes. */
function xmlIsRecord(el) {
  if (xmlOwnText(el)) return false;
  const tags = new Set();
  for (const c of el.children) {
    if (c.children.length || c.attributes.length || tags.has(c.tagName)) return false;
    tags.add(c.tagName);
  }
  return tags.size + el.attributes.length > 0;
}

/** Text as the dataset it is written as: numbers when it is numbers, else a string. */
function xmlTextDataset(ctx, text, attrs) {
  const numbers = xmlNumbers(text);
  if (numbers) return docDataset(ctx, attrs, numbers.length === 1 ? [] : [numbers.length], '<d', () => numbers);
  return docDataset(ctx, attrs, [], 'S', () => [text]);
}

/** Elements of one tag that are records, as a table: a column for each attribute and element. */
function xmlTable(els, ctx) {
  const keys = [];
  const seen = new Set();
  const add = (k) => { if (!seen.has(k)) { seen.add(k); keys.push(k); } };
  for (const el of els) {
    for (const a of el.attributes) add(`@${a.name}`);
    for (const c of el.children) add(c.tagName);
  }
  const group = easGroup({ note: `${docCount(els.length, `element ${els[0].tagName}`, `elements ${els[0].tagName}`)}: each attribute and element a column, its values over all of them in order.` });
  for (const key of keys) {
    if (docFull(ctx)) break;
    const raw = els.map((el) => {
      if (key.startsWith('@')) return el.hasAttribute(key.slice(1)) ? el.getAttribute(key.slice(1)).trim() : undefined;
      for (const c of el.children) if (c.tagName === key) return xmlOwnText(c);
      return undefined;
    });
    const present = raw.filter(v => v !== undefined && v !== '');
    const numbers = present.length && present.every(v => xmlNumber(v) !== undefined);
    const col = docColumn(raw.map(v => (v === undefined || v === '' ? undefined : numbers ? xmlNumber(v) : v)), 'XML_type');
    matPut(group, easLinkName(key), docDataset(ctx, col.attrs, [els.length], col.dtype, col.make));
  }
  return group;
}

/**
 * One element as the node it is written as, or null once a file has made
 * the groups and datasets it may.
 */
function xmlNode(el, ctx, depth) {
  if (docFull(ctx)) return null;
  const attrs = xmlAttributes(el);
  const text = xmlOwnText(el);
  if (!el.children.length) {
    if (text) return xmlTextDataset(ctx, text, attrs);
    if (el.attributes.length) return easGroup(attrs);
    return docDataset(ctx, { note: 'An empty element.' }, [], 'S', () => ['']);
  }
  const group = easGroup(attrs);
  if (depth > DOC_MAX_DEPTH) {
    group.attrs.note = `Elements nested more than ${DOC_MAX_DEPTH} deep are not shown.`;
    return group;
  }
  if (text) {
    const node = xmlTextDataset(ctx, text, {});
    matPut(group, '#text', node);
  }
  // The elements it holds, by tag in the order each first comes.
  const byTag = new Map();
  for (const c of el.children) {
    if (!byTag.has(c.tagName)) byTag.set(c.tagName, []);
    byTag.get(c.tagName).push(c);
  }
  for (const [tag, els] of byTag) {
    if (ctx.capped) break;
    if (els.length === 1) {
      const node = xmlNode(els[0], ctx, depth + 1);
      if (node) matPut(group, easLinkName(tag), node);
    } else if (els.every(xmlIsRecord)) {
      if (!docFull(ctx)) matPut(group, easLinkName(tag), xmlTable(els, ctx));
    } else {
      const names = docIndexNames(els.length, 1, s => `${tag}[${s}]`);
      for (let k = 0; k < els.length; k++) {
        const node = xmlNode(els[k], ctx, depth + 1);
        if (!node) break;
        matPut(group, easLinkName(names[k]), node);
      }
    }
  }
  return group;
}

/** An XML document from its text; an error that says where, when it is not one. */
function xmlParse(text) {
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  const error = [...doc.getElementsByTagName('parsererror')].find(e => e.namespaceURI === 'http://www.w3.org/1999/xhtml');
  if (error) {
    const said = error.textContent.replace(/\s+/g, ' ');
    const m = /error on line (\d+) at column (\d+):\s*(.*?)(?:\s*Below is a rendering.*)?$/.exec(said);
    throw new Error(m ? `${m[3].replace(/\.$/, '')} at line ${m[1]}, column ${m[2]}` : said.trim());
  }
  return doc;
}

/** An XML document as the tree easWriteHdf5 writes: its root element at the top. */
function xmlTree(fileName, doc, text) {
  const ctx = { nodes: 0, datasets: 0, capped: false };
  const rootEl = doc.documentElement;
  const declared = /^\s*<\?xml\s([^?]*)\?>/.exec(text.slice(0, 400));
  const field = (name) => (declared ? (new RegExp(`\\b${name}\\s*=\\s*["']([^"']*)["']`).exec(declared[1]) || [])[1] : undefined);
  const e = escapeHtml;
  const elements = doc.getElementsByTagName('*').length;
  const root = easGroup({
    Information: `<p>${e(fileName)}: XML, ${e(docCount(elements, 'element'))}, the root element ${e(rootEl.tagName)}.</p>`,
    XML_format: 'XML',
    XML_version: field('version'),
    XML_encoding: field('encoding')
  });
  const node = xmlNode(rootEl, ctx, 1);
  if (node) matPut(root, easLinkName(rootEl.tagName), node);
  if (ctx.capped) root.attrs.note = `Only the first ${DOC_MAX_NODES.toLocaleString('en-US')} elements and values are shown.`;
  return { tree: root, datasets: ctx.datasets };
}

/**
 * Open an XML file: its elements written as an HDF5 file in memory and
 * registered under the file's own name. Does not refresh the tree.
 *
 * @param {string} fileName - Display name
 * @param {ArrayBuffer} buffer - The file's bytes
 * @param {string} [context] - Label for failure reporting
 * @returns {Promise<string[]>} The name it was registered under
 */
async function ingestXmlFile(fileName, buffer, context = 'ingestXmlFile') {
  docCheckSize(fileName, buffer);
  setFileLoadProgress(null, `${fileName} — reading it…`);
  await yieldForPaint();
  const text = docDecode(buffer);
  let doc;
  try {
    doc = xmlParse(text);
  } catch (err) {
    throw new Error(`${fileName} could not be read as XML: ${err.message}.`);
  }
  const { tree, datasets } = xmlTree(fileName, doc, text);
  doc = null;
  return docOpen(fileName, tree, datasets, context);
}
