# Safety helper tests

    node resources/tests/safe/run-safe.js

Unit tests for `resources/js/kvot-safe.js`, the four points where data from
outside the program crosses into somewhere it could be interpreted rather than
displayed. Each case is something that went wrong, or could have:

- **`kvotEscapeHtml`** — there were four independent HTML escapers on this site,
  two of which did not escape the apostrophe. An attribute written with single
  quotes would have been as exposed as one with double quotes is without
  `&quot;`.
- **`kvotSafeHttpUrl`** — a Zotero record URL went into an `href` with escaping
  but no scheme check. `javascript:alert(1)` contains no character an escaper
  touches, so it would have been written through unchanged and been a live
  link. The Zotero settings panel accepts any `http(s)` endpoint the user
  names, so the response is not trusted to that extent.
- **`kvotCsvCell`** — a QA comment typed as `=HYPERLINK(...)` in a source
  workbook was written to the CSV export unchanged and ran as a formula when
  the export was opened. Negative numbers are deliberately left alone, so the
  fix does not turn real data into text.
- **`kvotFileTooLarge`** — uploads were read into memory whole with no ceiling,
  so a mis-dragged file gave no error and no progress, only a tab that stopped
  responding.

The file is a classic browser script, so its top-level `const` bindings are
visible to later scripts but are not properties of the global object; the
harness appends a short epilogue to hand them out rather than changing how the
file behaves in a page.
