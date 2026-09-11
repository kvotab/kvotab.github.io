/*
  Unit tests for resources/js/kvot-safe.js.

  These four helpers are the points where data from outside the program crosses
  into somewhere it could be interpreted rather than displayed, so each case
  below is a thing that went wrong, or could have:

    * two of the four HTML escapers this replaced did not escape the apostrophe
    * a Zotero record URL went into an href with no scheme check, so
      "javascript:..." — which contains nothing an escaper touches — would have
      been a live link
    * a QA comment typed as "=HYPERLINK(...)" was written to CSV unchanged and
      ran as a formula when the export was opened
    * an oversized upload was read into memory with no ceiling and no message

  Run:  node resources/tests/safe/run-safe.js
*/
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

/*
  The file is a classic browser script, not a module: its top-level `const`
  bindings are visible to the scripts that load after it but are not properties
  of the global object. A short epilogue hands them out so the same file can be
  exercised here without changing how it behaves in a page.
*/
const source = fs.readFileSync(path.join(__dirname, '../../js/kvot-safe.js'), 'utf8');
const sandbox = {};
vm.runInNewContext(source + `
  globalThis.__api = {
    kvotEscapeHtml, kvotSafeHttpUrl, kvotCsvCell,
    kvotFileTooLarge, kvotFormatBytes, KVOT_FILE_SIZE_LIMITS
  };`, sandbox, { filename: 'kvot-safe.js' });
const {
  kvotEscapeHtml, kvotSafeHttpUrl, kvotCsvCell, kvotFileTooLarge,
  kvotFormatBytes, KVOT_FILE_SIZE_LIMITS
} = sandbox.__api;

const failures = [];
const is = (got, want, label) => {
  if (got !== want) failures.push(`${label}\n      want ${JSON.stringify(want)}\n      got  ${JSON.stringify(got)}`);
};

/* ── escaping ── */
is(kvotEscapeHtml(`<a href='x' title="y">&`), '&lt;a href=&#39;x&#39; title=&quot;y&quot;&gt;&amp;', 'all five characters escaped');
is(kvotEscapeHtml('a&lt;b'), 'a&amp;lt;b', 'ampersand replaced first, so nothing is escaped twice');
is(kvotEscapeHtml(null), '', 'null becomes empty');
is(kvotEscapeHtml(undefined), '', 'undefined becomes empty');
is(kvotEscapeHtml(0), '0', 'zero is not treated as absent');

/* ── link schemes ── */
for (const url of ['https://www.zotero.org/groups/1/items/AB', 'http://x.test/p?q=1#f',
                   '//cdn.test/x.js', '/relative/path', 'relative.html', '#fragment']) {
  is(kvotSafeHttpUrl(url), url, `kept: ${url}`);
}
for (const url of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'java\tscript:alert(1)',
                   ' javascript:alert(1)', 'data:text/html,<script>x</script>',
                   'vbscript:msgbox', 'file:///etc/passwd', 'blob:http://x/y']) {
  is(kvotSafeHttpUrl(url), '', `blocked: ${JSON.stringify(url)}`);
}

/* ── spreadsheet cells ── */
is(kvotCsvCell('=HYPERLINK("http://e","x")'), '"\'=HYPERLINK(""http://e"",""x"")"', 'formula neutralised and quotes doubled');
is(kvotCsvCell('+1'), '"\'+1"', 'leading plus neutralised');
is(kvotCsvCell('@SUM'), '"\'@SUM"', 'leading at neutralised');
is(kvotCsvCell('\tx'), '"\'\tx"', 'leading tab neutralised');
is(kvotCsvCell('-cmd|calc'), '"\'-cmd|calc"', 'leading minus neutralised when not a number');
is(kvotCsvCell('-5'), '"-5"', 'negative integer left alone');
is(kvotCsvCell('-5.5e3'), '"-5.5e3"', 'negative decimal left alone');
is(kvotCsvCell('say "hi"'), '"say ""hi"""', 'embedded quotes doubled');
is(kvotCsvCell('plain text'), '"plain text"', 'ordinary text untouched');
is(kvotCsvCell(null), '""', 'null becomes an empty cell');

/* ── upload ceiling ── */
is(kvotFileTooLarge({ name: 'a.pdf', size: 1024 }).tooLarge, false, 'small file accepted');
is(kvotFileTooLarge({ name: 'a.pdf', size: 300 * 1024 * 1024 }).tooLarge, true, 'oversized document rejected');
is(kvotFileTooLarge({ name: 'a.h5', size: 300 * 1024 * 1024 }, KVOT_FILE_SIZE_LIMITS.dataset).tooLarge, false,
   'the dataset limit is higher than the document limit');
is(kvotFileTooLarge({ name: 'x' }).tooLarge, false, 'a file with no size is not rejected');
const big = kvotFileTooLarge({ name: 'report.pdf', size: 400 * 1024 * 1024 });
is(big.reason.includes('report.pdf') && big.reason.includes('400 MB'), true,
   'the reason names the file and its size');
is(kvotFormatBytes(1536), '1.5 kB', 'bytes formatted as kB');
is(kvotFormatBytes(5 * 1024 * 1024), '5.0 MB', 'bytes formatted as MB');
is(kvotFormatBytes(0), '0 B', 'zero bytes');

if (failures.length) {
  console.error(`${failures.length} failure(s):`);
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log('kvot-safe tests passed (escaping, link schemes, CSV cells, upload ceiling).');
