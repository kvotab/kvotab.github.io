# Changelog

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
