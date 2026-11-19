# SKB QC Summary tests

`test-ui.py` drives `skb_qa_summary.html` in headless Chrome over CDP and
checks how workbooks get in: dropped or chosen one by one, or as whole
folders. Every row records the folder its workbook came from. It also checks
what the page makes of them: parameters and their flags, the filters, the
Files view, the calculation cases and the input-set exports traced back to
the source rows.

    python3 -m http.server 8765          # from the repository root
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9222 --no-first-run \
      --user-data-dir=<a fresh directory> about:blank
    python3 resources/tests/skb_qa_summary/test-ui.py

`QC_HTTP_PORT` and `QC_CDP_PORT` choose other ports. The suite takes a few
seconds and exits 0 when every check passes. It needs `openpyxl` and
`websockets`.

`test-config.mjs` checks, in Node, the rules that tie a calculation case to its
workbooks (`resources/js/skb-qa-config.mjs`). It parses small TOML texts with
the page's own copy of smol-toml:

    node resources/tests/skb_qa_summary/test-config.mjs

`test-xlsx-stream.mjs` checks, in Node, the streaming reader the page reads
`.xlsx` and `.xlsm` workbooks with (`resources/js/xlsx-stream.mjs`) and what
it makes of a workbook (`resources/js/skb-qa-read.mjs`):

    node resources/tests/skb_qa_summary/test-xlsx-stream.mjs

It writes its workbooks itself, part by part and ZIP entry by ZIP entry, so
that each case is exactly the XML it is about: shared and inline strings,
rich text with phonetic runs, XML and `_xHHHH_` escapes, a formula's cached
text, booleans and errors, cells without a reference, column AB, a sheet
whose rows start at 3 and one whose header sits below empty rows, 30 000 rows
deflated and stored (a row split where the inflater's chunk ends was once
lost), and what is not a workbook. Node before 21 has no `deflate-raw`
DecompressionStream; the test puts zlib in its place.

## Calculation cases

TOML files are read beside the workbooks. `link.toml` and `data.toml` are
special, and every other TOML file is a calculation case. The rules are those
the calculation-case code applies when it builds the parameter files:

- a case's `parameter_files`, and a domain's own, are `<set>.h5`, built by
  the input set `<set>` of `link.toml`;
- a set lists its data files under `files`, or takes those of `init_file`
  without its `skip` and with its `add`. A `_det` name is the deterministic
  copy of a data file;
- a data file's workbook is `<path>/<name>.xlsx` under the Excel folder, and
  `sheet_names` keeps only those sheets. With a `raw_path` it also has raw
  data, which may stand in for the workbook: its workbook is looked for all
  the same, and only one without raw data lacks it when none is found.

`test-config.mjs` checks these rules on their own: chains, loops, skips of
names a set does not have, which copy of a workbook is taken, and the checks
the page lists. A set or data file called `constructor` must stay a name.
`test-ui.py` writes a configuration of three cases, with a broken TOML file
beside them. It drops the config folder alone, then its Excel folder, and
checks each case's input, the QC counted from its workbooks, the case filter
(only the sheets `data.toml` names) and the case details. One case's
description carries `<b>`, a `<script>` and an `<img onerror>`: the bold must
show, and nothing may run.

Real configurations are client data, never part of this repository. To try
one, drop its config and excel folders on the page.

## Input-set exports

An export is the workbook the calculation-case code writes for an input set
(`<set>.h5`): one row per value, with the workbook, sheet and row it was read
from in the columns `file`, `sheet` and `row`. The page reads only those
columns, `id` and `time` and `linked_file`, in workers, and traces each value
to its QC row once every workbook is read:

- a source is matched by its path below the folder called `excel`, so an
  export made on another machine still finds `excel/base_case/x.xlsx`;
- an ID on one row is that row; a time point (a value with a time) is the
  next of its ID's rows, since the export gives a time point its place among
  the sheet's time series rather than its row; a value without a time on
  several rows is the row the export names, or the last, which the import
  kept;
- the rest is counted by why: raw data (a source outside an `excel` folder,
  or none), a workbook not read, a sheet without the QC columns, a row no
  longer there. A workbook not read, or a row no longer there, makes the
  export out of date.

`test-ui.py` writes an Excel folder and a QC folder with one value of each
kind, and a time series whose rows the export gives wrongly. It checks the
counts and the rows traced, the Input set filter, the Files view under a
reviewer filter, the export's sources when opened, the file list as CSV, and
the same tracing with `window.Worker` taken away, which reads on the page.

## The fixture

Nothing is checked in. The suite builds its workbooks in a temporary folder
with openpyxl, plus one `.xls` that it writes with the page's own SheetJS
(openpyxl cannot write BIFF), and removes the folder afterwards. The tree
holds, on purpose:

- two workbooks called `params.xlsx` in two folders. They must count as two
  files, and the ID they share as two parameters, neither flagged for it: a
  variant's workbook gives its own value for an ID of the common one;
- a parameter whose two rows disagree on status, under two reviewers, which
  must be flagged for both;
- a `.xlsm`, an `.xls` and a sheet still headed QA rather than QC;
- a sheet whose header is in row 3. Reading only the first row of each sheet
  cannot see that header, so this sheet must be read in full, and its Excel
  rows must come out as 4 and 5, not 2 and 3;
- a data sheet before the QC sheet, so the sheet indices of the quick first
  read and the full read must agree;
- what a real folder holds besides workbooks: an Excel `~$` owner file, a
  macOS `._` copy, a hidden folder with a valid QC workbook in it, and a text
  file. None of them may be read;
- a workbook cut short (a plain text file will not do here: SheetJS reads text
  as a one-cell sheet), a folder with no workbook, and twelve small workbooks
  for stopping a read part-way.

## How the browser is driven

- **Folder drop**: `Input.dispatchDragEvent` with a directory path in
  `data.files`. The page gets a trusted drop whose item has a real
  `FileSystemDirectoryEntry`, and walks it as it would a folder from Finder.
- **Folder picker**: `DOM.setFileInputFiles` with a directory path on the
  `webkitdirectory` input. Every file arrives with its `webkitRelativePath`.
- **Waiting for a read**: every read replaces the page's `queue` promise. The
  suite keeps the old one, waits until it has been replaced (which proves the
  read was queued), then awaits `queue` until it stops changing. Polling for
  "nothing is being read" can return before the drop has been handled at all.
- **Stop and Clear all part-way**: a `MutationObserver` on the status line
  clicks the button as soon as "Reading 3 of 12" appears. The observer runs
  before the page reads the next workbook, so the result is the same on every
  run: three workbooks are kept on Stop, none on Clear all.
- **Which chooser opened**: with `Page.setInterceptFileChooserDialog`, the
  `Page.fileChooserOpened` event names the input by `backendNodeId`. Both
  inputs sit inside the drop zone, so the click a button passes to its input
  also reaches the zone. Taking that click once made "Choose a folder" open
  the file chooser instead. The suite clicks and presses Enter on each button
  and checks which input opened.
- **An item with no entry** (a mail attachment, say) is a synthetic drop of a
  `File` made in the page. Chrome gives such an item no `webkitGetAsEntry()`,
  so this reaches the branch that takes it as a file on its own.
- **SheetJS**: the page loads its own copy from `vendors/js/`. The suite
  checks that the loaded `XLSX.version` is the one in the file name, and that
  it is 0.20.2 or later. Versions before 0.19.3 have a prototype-pollution
  flaw (CVE-2023-30533) and versions before 0.20.2 a slow-regex flaw
  (CVE-2024-22363), both triggered by crafted files. Reading whole folders
  makes such a file more likely to reach the page.
- **Filters**: the page's own `setFilter(key, values)` sets a list, as a
  click in its popover does; `facetOptions(key)` and `facetCounts(key)` are
  what the popover lists.
- **Layout**: the page's width is compared with the window's at 1280 px, and
  on a 375 × 548 phone with touch emulated, where the search field must be
  16 px (iOS zooms into smaller ones and stays zoomed). In the dark theme,
  each summary tile's number must contrast 4.5:1 or more with its tile.
  Colours are read back through a canvas, because a `color-mix()` background
  computes to `color(srgb …)`, not `rgb()`.
