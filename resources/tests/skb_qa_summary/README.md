# SKB QC Summary tests

`test-ui.py` drives `skb_qa_summary.html` in headless Chrome over CDP and
checks how workbooks get in: dropped or chosen one by one, or as whole
folders. Every row records the folder its workbook came from.

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

## The fixture

Nothing is checked in. The suite builds its workbooks in a temporary folder
with openpyxl, plus one `.xls` that it writes with the page's own SheetJS
(openpyxl cannot write BIFF), and removes the folder afterwards. The tree
holds, on purpose:

- two workbooks called `params.xlsx` in two folders. They must count as two
  files, and the parameter they share must be flagged as "in 2 files";
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
- **Layout**: the page's width is compared with the window's at 1280 px, and
  on a 375 × 548 phone with touch emulated, where the filter fields must be
  16 px (iOS zooms into smaller ones and stays zoomed). In the dark theme,
  each summary card's number must contrast 4.5:1 or more with its card.
  Colours are read back through a canvas, because a `color-mix()` background
  computes to `color(srgb …)`, not `rgb()`.
