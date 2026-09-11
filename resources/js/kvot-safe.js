/* ==========================================================================
   SAFETY HELPERS  (site-wide)

   Loaded on every page, immediately after kvot-errors.js and before any page's
   own scripts.

   These four functions are the places where data from outside the program
   crosses into somewhere it could be interpreted rather than displayed:

     kvotEscapeHtml   text  -> HTML
     kvotSafeHttpUrl  text  -> an href
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
