# Changelog

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
