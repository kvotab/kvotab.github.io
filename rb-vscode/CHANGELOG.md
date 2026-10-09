# Changelog

## 0.1.9

* An Ecolego assessment (`.eas`) opens in the browser, as on the site: a
  file for each run it keeps, written as an HDF5 result file in memory, so
  the tree, the charts, comparing two runs and the exports work on it. Of
  several runs, a list in the page asks which to open. It opens from the
  Explorer, through Add Files, Open Together and a drop, and is always read
  whole (up to 1 GB). Rewritten on disk, it opens the same runs again.
* A run of an assessment can be saved, from the Python dialog, as the HDF5
  file the script reads.

## 0.1.8

* The extension's icon is the HDF5 Browser's own, the one rb.html shows in
  its tab: the HDF Group's H, its crossbar cut through as their mark's is,
  in the kvot mark's three tones.
* From the site: an axis's unit can take a prefix, chosen beside its lin/log:
  *k* shows Bq as kBq, the values divided by 1000. A preset can carry one of
  its own. The Excel export writes the chart's values in the axis's units;
  CSV and the Python script keep the file's.
* From the site: the gear opens the axis presets in a window of its own,
  beside the chart and moved by its title bar: the chart's axes on top, to
  set by hand, and the saved presets below, each used with a click, edited,
  updated or deleted.
* From the site: Show Total, Same chart, Show Ratio and an iteration keep the
  preset that is selected, and a zoom carried from a linear time axis to a
  log one stays the stretch of time it was.
* From the site: a file's *Information*, shown when the pointer is over its
  tab, goes through the same sanitiser as the rest of a file's markup. A
  crafted file's could send the page elsewhere or load a stylesheet.

## 0.1.7

* From the site: the Excel exports of a chart and of a dataset are written as
  asked. Every cell's format was one style late (the header plain, the cells
  after it bold), no number format reached its cell, and Excel had to repair
  the file; the header is now bold, the numbers in their formats, and the
  file opens as it is.
* From the site: the normal and lognormal distributions of a parameter, the
  values the information panel draws of them and the curves laid over a
  chart, are exact in their far tails. The error function they rest on had
  its complement about three times too large beyond four and gave no number
  past 9.2; the normal's probabilities and percentiles are now taken from
  the complement, which keeps the lower tail's digits.

## 0.1.6

* From the site: a chart's *Python* button, among its controls, gives the
  chart as a matplotlib script that draws it from the HDF5 files, each line
  computed as the page computes it (a mean over realisations, the CI and SEM
  bands, Show Total, a realisation), in the page's colours, dashes, legend and
  axes. *Download* in its dialog saves it through VS Code's Save dialog, and a
  saved script can be opened from the message that says it was saved.
* From the site: a dataset whose name has markup in it is only its text in
  the Excel export (an `<img onerror>` in one ran in the page before), and a
  group whose name has a line break in it opens in the tree.

## 0.1.5

* The extension updates itself from kvotab.se. Twice a day (soon after
  VS Code starts, unless it looked in the last twelve hours, and every twelve
  hours while it runs) it reads the site's release note; a newer version is
  downloaded, checked and installed, and the window offers *Reload Window* to
  start it. *HDF5 Browser: Check for Updates*, in the Command Palette and the
  extension's gear menu, looks at once. `hdf5Browser.updates` (`install`,
  `notify` or `off`) says what a new version leads to, and VS Code's own
  Auto Update and Auto Check Updates settings, when off, hold it back.
* Only a release signed with kvotab's release key is installed: the note's
  signature covers the version and the package's SHA-256, and is checked
  with the key the extension carries.
* This is the last version to install by hand: the ones after it arrive by
  themselves.

## 0.1.4

* From the site: a group whose index list is Pathways or Exposed groups draws
  a chart of its members, as a Repositories group does, and their lines have
  colours of their own, in the hues of the PSAR dose and pathway charts.

## 0.1.3

* Several files dropped at once go into one browser, as its file tabs, also
  when no browser was open: VS Code opens a tab each and loads only the one
  it shows, and that browser now takes the others. The extension starts
  when VS Code has started (`onStartupFinished`), so it sees them opened.

## 0.1.2

* The extension's icon is kvotab's logo, the site's favicon (as rb.html's
  is now too, where it was SKB's).

## 0.1.1

* *Download Excel*: the chart is on white round and behind the plot, in the
  light theme's colours whatever the view is in; a background overlay's
  phases are lines along the time they span, which follow the time axis if
  its scale or limits are changed in Excel, in every panel.
* A view served by an older copy of the extension, still running after an
  update of the same version was installed over it, says to reload the
  window. Installing 0.1.0 over 0.1.0 had left "Download Excel" failing
  (`downloadChartDataAsExcel is not defined`) until the window was reloaded.
  Each release now has a version of its own, so VS Code keeps the old one
  running until the reload instead of mixing the two.

## 0.1.0

The first version: kvotab.se's HDF5 Browser as a VS Code editor for `.h5`,
`.hdf5` and `.he5` files, built from the site's own scripts.

* Files under 256 MB are read whole; larger ones a piece at a time by h5wasm in
  the extension host (`hdf5Browser.readLazily`).
* Open Together, Add Files, Save through VS Code's dialogs, reread on change.
* A file dropped on a browser, from the Explorer or the Finder, goes into it
  as another file tab (`hdf5Browser.addToOpenBrowser`, on by default).
* The header is the file tabs alone, standing on its line, with Add Files and a
  light/dark toggle at the right; the toggle's choice is kept in
  `hdf5Browser.theme` for every view, and `auto` follows VS Code's theme.
* No network: every library is bundled, checked against the site's pins.
