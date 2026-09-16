/* ==========================================================================
   SAFETY HELPERS  (site-wide)

   Loaded on every page, immediately after kvot-errors.js and before any page's
   own scripts.

   These four functions are the places where data from outside the program
   crosses into somewhere it could be interpreted rather than displayed:

     kvotEscapeHtml   text  -> HTML
     kvotSafeHttpUrl  text  -> an href
     kvotSanitizeHtml markup from a file -> a DOM fragment
     kvotCsvCell      text  -> a spreadsheet cell
     kvotFileTooLarge a file -> the whole thing in memory

   They live together because they are all the same kind of decision, and
   because there was previously one implementation of each per page: four
   separate copies of the HTML escaper existed, of which two escaped the
   apostrophe and two did not.
   ========================================================================== */

/*
  The five characters that change meaning inside markup. The apostrophe matters
  as much as the double quote — an attribute written with single quotes is just
  as common — and leaving it out is the kind of gap that stays invisible until
  the first single-quoted attribute is written years later.

  Order matters: the ampersand has to go first, or the entities produced by the
  later replacements get escaped a second time.
*/
const KVOT_HTML_ENTITIES = Object.freeze({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
});

/**
 * Escape text for interpolation into HTML, including into an attribute value.
 *
 * @param {*} value - Anything; null and undefined become the empty string
 * @returns {string}
 */
function kvotEscapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => KVOT_HTML_ENTITIES[character]);
}

/**
 * A URL that is safe to put in an href, or the empty string.
 *
 * Escaping is not enough here. `javascript:alert(1)` contains no character
 * that kvotEscapeHtml would touch, so an escaped string can still be an
 * executable URL — the scheme has to be checked separately. Anything that is
 * not plainly http or https is rejected, which also covers `data:`, `blob:`
 * and `vbscript:`.
 *
 * Protocol-relative (`//host/path`) and relative URLs are accepted, since they
 * inherit the page's own scheme and cannot introduce a new one.
 *
 * @param {*} value
 * @returns {string} The URL, or '' when it is not safe to link to
 */
function kvotSafeHttpUrl(value) {
  const url = String(value ?? '').trim();
  if (!url) return '';
  /* A leading control character or whitespace can hide the scheme from a
     naive check while the browser still honours it. */
  const bare = url.replace(/[\u0000-\u0020]/g, '');
  if (/^(?:https?:)?\/\//i.test(bare)) return url;
  /* No scheme at all: a relative path or fragment, which is safe. */
  if (!/^[a-z][a-z0-9+.-]*:/i.test(bare)) return url;
  return '';
}

/* ──────────────────────────────────────────────────────────────────────────
   Markup that came from a file

   Escaping is the right answer whenever the text is meant to be read as text.
   This is for the other case: a value that is *meant* to carry a little
   formatting - an HDF5 "information" attribute written by whoever produced the
   file - and therefore has to be parsed as markup and cannot simply be escaped.

   Two rules, both learned the hard way:

   1. An allowlist, never a denylist. A denylist has to be right about every
      element and attribute that exists now or ever will; an attacker needs one
      gap. The version this replaces stripped script, iframe, object, embed,
      on* handlers and javascript: hrefs - and still let through <base>,
      <meta http-equiv=refresh>, <style>, <link>, <form action=javascript:>,
      <button formaction=javascript:> and <svg><a xlink:href=javascript:>. The
      <base> alone repointed every relative URL on the page at another origin.

   2. Return a fragment, never a string. Sanitising to a string that the caller
      then assigns to innerHTML re-parses it, and a second parse of once-parsed
      markup is exactly the shape mutation-XSS attacks take. A fragment cannot
      be re-interpreted.

   Elements are rebuilt rather than cleaned in place, so an attribute can only
   appear on the output by being copied there deliberately.
   ────────────────────────────────────────────────────────────────────────── */

/*
  Tags that may appear, and the attributes each may keep. Anything absent is
  unwrapped - its text survives, the element does not.

  Deliberately absent, beyond the obvious script/iframe/object/embed:
    base, meta, link   can redirect the page or the URLs it resolves
    style              can hide, move or impersonate the interface around it,
                       and exfiltrate through selectors and background: url()
    form, button       carry action= and formaction=, which take javascript:
    svg, math          separate namespaces whose parsing rules differ from
                       HTML's, which is where mutation-XSS lives
  Also absent everywhere: class, id and name. Borrowing the site's own classes
  is enough to impersonate its interface, and id/name on an injected element
  can shadow a real one out from under the code that expects it.
*/
const KVOT_HTML_ALLOWED = Object.freeze({
  a: ['href', 'title'], abbr: ['title'], b: [], blockquote: [], br: [],
  caption: [], code: [], dd: [], div: [], dl: [], dt: [], em: [], h1: [],
  h2: [], h3: [], h4: [], h5: [], h6: [], hr: [], i: [], kbd: [], li: [],
  ol: [], p: [], pre: [], q: [], s: [], samp: [], small: [], span: [],
  strong: [], sub: [], sup: [], table: [], tbody: [], td: ['colspan', 'rowspan'],
  tfoot: [], th: ['colspan', 'rowspan'], thead: [], tr: [], u: [], ul: [], var: []
});

/*
  Elements whose *content* is no more welcome than the element: a <style> body
  is a stylesheet, a <script> body is a program. Everything else not on the
  allowlist is unwrapped instead, so ordinary prose inside an unexpected tag is
  still shown.
*/
const KVOT_HTML_DROP_WHOLE = Object.freeze(new Set([
  'script', 'style', 'template', 'iframe', 'object', 'embed', 'base', 'meta',
  'link', 'form', 'noscript', 'svg', 'math', 'title', 'head'
]));

/* A crafted value can nest thousands of elements deep; recursion that follows
   it lands on the stack limit and takes the page down with it. */
const KVOT_HTML_MAX_DEPTH = 40;

/**
 * Parse markup from an untrusted source into a DOM fragment, keeping only
 * elements and attributes that cannot change what the page does.
 *
 * @param {*} html - Markup as a string; null and undefined give an empty fragment
 * @returns {DocumentFragment} Safe to append. Never re-serialise and re-parse it.
 */
function kvotSanitizeHtml(html) {
  /* A <template>'s content is inert: parsed, but not connected to the
     document, so nothing in it loads, runs or is fetched while we look at it. */
  const template = document.createElement('template');
  template.innerHTML = String(html ?? '');
  return kvotCleanNodes(template.content.childNodes, 0);
}

function kvotCleanNodes(nodes, depth) {
  const out = document.createDocumentFragment();
  for (const node of Array.from(nodes)) {
    const cleaned = kvotCleanNode(node, depth);
    if (cleaned) out.appendChild(cleaned);
  }
  return out;
}

function kvotCleanNode(node, depth) {
  if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.data);
  if (node.nodeType !== Node.ELEMENT_NODE) return null;   // comments, and the rest

  const tag = String(node.localName || '').toLowerCase();
  if (KVOT_HTML_DROP_WHOLE.has(tag)) return null;

  /* Past the depth limit everything collapses to its text, which keeps the
     content without following the nesting any further. */
  if (depth >= KVOT_HTML_MAX_DEPTH) return document.createTextNode(node.textContent || '');

  const allowedAttrs = KVOT_HTML_ALLOWED[tag];
  if (!allowedAttrs) return kvotCleanNodes(node.childNodes, depth + 1);   // unwrap

  /* Built fresh rather than cloned: nothing carries over that is not copied
     across on purpose below. */
  const el = document.createElement(tag);
  for (const name of allowedAttrs) {
    if (!node.hasAttribute(name)) continue;
    const value = node.getAttribute(name);
    if (name === 'href') {
      const safe = kvotSafeHttpUrl(value);
      if (safe) el.setAttribute('href', safe);
      continue;
    }
    el.setAttribute(name, value);
  }
  el.appendChild(kvotCleanNodes(node.childNodes, depth + 1));
  return el;
}

/*
  A spreadsheet treats a cell beginning =, +, @ or a control character as a
  formula, so text that came from outside becomes code as soon as the exported
  file is opened. Prefixing an apostrophe forces it back to text.

  The minus sign is deliberately not in that set on its own: -5 is a number,
  and prefixing every negative value would turn real data into strings. It is
  escaped only when what follows is not a number.
*/
const KVOT_CSV_FORMULA_START = /^[=+@\t\r\n]/;

/**
 * Quote a value for a CSV cell, neutralising spreadsheet formula injection.
 *
 * @param {*} value
 * @returns {string} The quoted cell, including its surrounding double quotes
 */
function kvotCsvCell(value) {
  let text = String(value ?? '');
  const startsFormula = KVOT_CSV_FORMULA_START.test(text)
    || (text.startsWith('-') && !/^-\d/.test(text));
  if (startsFormula) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

/*
  Everything on this site is processed in the browser, so an uploaded file is
  read into memory in full. Without a ceiling a mis-drag of a multi-gigabyte
  file gives no error and no progress — just a tab that stops responding — and
  the reason never reaches the user.

  The limit is generous: the largest real document these tools are built for is
  a few hundred pages of PDF, and the largest HDF5 result set a few hundred
  megabytes.
*/
const KVOT_FILE_SIZE_LIMITS = Object.freeze({
  document: 256 * 1024 * 1024,
  dataset: 1024 * 1024 * 1024
});

/**
 * Format a byte count the way a person reads one.
 *
 * @param {number} bytes
 * @returns {string}
 */
function kvotFormatBytes(bytes) {
  const units = ['B', 'kB', 'MB', 'GB', 'TB'];
  let value = Number(bytes) || 0;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
  return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/**
 * Whether a file is too large to read into memory, with a reason to show.
 *
 * @param {File|Blob} file
 * @param {number} [limitBytes] - Defaults to the document limit
 * @returns {{tooLarge: boolean, reason: string}}
 */
function kvotFileTooLarge(file, limitBytes = KVOT_FILE_SIZE_LIMITS.document) {
  const size = file && Number(file.size);
  if (!Number.isFinite(size) || size <= limitBytes) return { tooLarge: false, reason: '' };
  return {
    tooLarge: true,
    reason: `${file.name || 'The file'} is ${kvotFormatBytes(size)}, over the `
      + `${kvotFormatBytes(limitBytes)} this page can process in the browser. `
      + 'Split it, or export a smaller extract.'
  };
}
