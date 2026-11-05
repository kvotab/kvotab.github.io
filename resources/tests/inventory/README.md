# Tests for canister_inventory.html

Two of them. `test-model.mjs` is the file readers and the arithmetic and needs
only Node; `test-ui.py` is the page and needs a server and a headless Chrome
(other ports than 8765 and 9222 with `INV_HTTP_PORT` and `INV_CDP_PORT`).

    node resources/tests/inventory/test-model.mjs
    python3 -m http.server 8765
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
        --remote-debugging-port=9222 --user-data-dir=<fresh dir> about:blank
    python3 resources/tests/inventory/test-ui.py

Both exit 0 when every check passes. `test-ui.py` needs websockets and
openpyxl.

Every file the tests read is made by the tests, from made-up numbers: an
inventory in JSON, and a workbook and a report shaped as SKB's PSAR files
are. Neither the inventories the page is built for nor PSAR's
numbers are in the repository; they are not ours to publish.

## Real files

With a real inventory (.json, or a .json in a .zip archive), and PSAR's
workbook and report, in one folder,

    python3 resources/tests/inventory/make-local-fixtures.py <folder>

writes `local/expected.json` (git-ignored): where the files are, and what
Python reads from them. Nothing is copied. `test-model.mjs` then also checks
the page's readers against it, and says so; without it, it skips them.

## What test-model.mjs checks, and against what

- **Reading the inventory** against the object it was made from: every
  amount, the canisters, elements, parts, nuclides, dates and fields; the
  same when the file arrives in slices of 1, 3, 64 and 4093 bytes (a canister
  split anywhere); an array of canisters with arrays of elements; NaN as
  Python writes it; names with quotes and backslashes; a nuclide first seen
  part of the way through; broken JSON refused with a reason.
- **Decay** against the definitions: a lone nuclide as exp(−λt), Am-241 grown
  from Pu-241 against the two-member Bateman solution (to 1e-10), the decay
  heat of Cs-137 with Ba-137m in equilibrium from ICRP 107's energies, A = λN
  and the atomic mass for the units, PSAR's half-life replacing ICRP 107's,
  a reference brought to a later year and refused for an earlier one, its
  becquerels made moles with the half-lives it was worked out with and
  decayed with those in use; below
  the solver's round-off, H-3 a thousand years on as exp(−λt), and what
  Am-242m feeds 0 once Am-242m has run down.
- **Planned elements** (named PLAN...): told by their names; with planned or
  discharged elements only, a canister's sums, its elements, its count and
  its heat from the file are of those alone, and a canister holding none is
  left out; one choice asked for beside another.
- **The inventory**: canister types from their elements, PSAR's categories
  from the reactors' names, the first year after the last packing, a
  canister's part as the sum of its elements', each canister decaying from
  its own date, elements as their canister, percentiles as Excel's.
- **PSAR's report**: Table D-1's half-lives (two nuclides to a row),
  Table D-2's totals by kind of fuel and part with the number of elements and
  PWR's control rods, Table E-7's average canisters and their spread as
  fractions, a Table E canister by part, the year and the number of canisters
  from the text. The .docx is zipped by the test.
- **PSAR's workbook**, written by SheetJS: the average canister and the
  canister count (not the note beside it), swap MOX BWR and PWR summed, the
  rod skeletons, the average PWR canister with its spread and its parts in an
  element's shares (control rods per element), the encapsulation simulation
  and its reactor codes as names.
- **Zipped files**, in archives written by the test: the directory of a zip
  and of a zip64 archive (64-bit sizes, offsets and directory), names in
  UTF-8, folders and macOS's own files passed over; the inventory in them
  read as it unpacks and the same as the file, every packed byte counted for
  the progress; a stored entry; a gzip file, and one cut short refused; an
  encrypted entry and a file that is no zip archive refused with a reason.
- **Excel files** (inventory-excel.js through SheetJS), read back by SheetJS:
  sheet names Excel takes, each once; numbers whole, in their formats; a date
  as Excel's own day number; what is no number an empty cell; text that looks
  like a formula kept as text; a filter on the headings.
- **Real files** (with `local/`): the inventory read from its zip archive if
  it is in one, every part and nuclide totalled as Python's json module reads
  them, the decay heat from the nuclides against the file's for the median
  canister, the report's average BWR and PWR canisters (Table E-7) against
  the workbook's, and every table of the report found.

## What test-ui.py checks

The start (drop zone, tabs, Help); a broken JSON and a file of another kind
reported in the bar; the three files opened together from one zip archive (in
a folder, beside macOS's own files and a text file, passed over quietly) and
shown as chips, the inventory named by its archive; the Overview's numbers
and charts with PSAR's beside them; the planned part (a planned element
in every made-up canister) in the Overview's numbers, its charts hatched,
the Fuel setting narrowing every view to planned or discharged elements;
PSAR's half-lives offered, and PSAR's becquerels made moles with them
(the made-up Table D-1 gives Ni-59 PSAR's 76 000 years); a year from
the last packing, a year too early marked while the one in use stays; the
Nuclides table, chart and unit, CSV saved; every canister and element, Show more, an element name that
is markup kept as text, a click opening its canister; the curves over time
with PSAR's dashed beside them, offered only of the same kind as what is
drawn (average canisters of its type, or totals for all canisters together),
each named by its document, and the note saying PSAR's were brought to the
year shown; the ratio chart only when both hold for one
year, the button that sets it, the totals by kind of fuel, the reactors; a
gzipped inventory dropped (CDP's `Input.dispatchDragEvent`); the dark theme;
a 390 px phone with no sideways scroll and 16 px fields; the full window
(no site header or footer, the page the window's height, the kvot mark and
the theme switch in the tab row, an (i) panel the window's height, kept and
undone); no error on the page.

Every view's Excel file is saved and read back by openpyxl: the Overview's
sheets with the canisters beside PSAR's and an About sheet naming the
inventory, the time and PSAR's workbook; the Nuclides table with its numbers
in 0.000E+00; every canister with every nuclide and its packing date as a
date; every element with the planned ones marked; every nuclide over time
and PSAR beside it; and a sheet for each table of the comparison.

The page keeps its views' settings in localStorage (`kvot.inventory`); the
test clears them and reloads before it starts.
