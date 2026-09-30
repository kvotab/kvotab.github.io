# HDF5 Browser for Visual Studio Code

The [HDF5 Browser](https://kvotab.se/rb.html) from kvotab.se, as an editor for
`.h5`, `.hdf5` and `.he5` files. Open a file from the Explorer and it opens in
an editor tab: the file's tree, each dataset's attributes and values, and the
charts, with every feature the page has on the web — radionuclide groups with
their total, several groups a panel each or in one chart, confidence bands and
iterations, log axes and presets, intersect and union of several files,
search, and export to CSV and Excel.

It is the same page, not a copy of it: the build takes the site's own scripts,
so the extension shows what kvotab.se shows.

## Installing

Download the latest version from the **VS Code** button on
[kvotab.se/rb.html](https://kvotab.se/rb.html): the file is
`hdf5-browser-<version>.vsix`. In VS Code, open the Extensions view
(<kbd>⇧⌘X</kbd>, or <kbd>Ctrl+Shift+X</kbd>), choose *Install from VSIX…* in
its *…* menu and pick the file; or, in a terminal,
`code --install-extension hdf5-browser-<version>.vsix`. Reload the window when
VS Code asks.

## Updates

From 0.1.5 on, the extension keeps itself up to date: it comes from the site,
not from the Marketplace, so VS Code never looks for a newer version of it, and
the extension looks itself. It reads the site's release note twice a day —
soon after VS Code starts, unless it looked in the last twelve hours, and
every twelve hours while VS Code runs. A newer version is downloaded, checked
and installed as *Install from VSIX…* would install it, and the window offers
*Reload Window* to start it. *HDF5 Browser: Check for Updates* — in the
Command Palette, and in the extension's gear menu in the Extensions view —
looks at once.

A version is installed only if its release note is signed with kvotab's
release key, over the version and the package's SHA-256, and the package is
the one the note names. A site or a connection that was tampered with could
keep an update from arriving, but could not have anything else installed, nor
an older release passed off as newer.

`hdf5Browser.updates` says what a new version leads to: `install` (the
default), `notify` (offered; installed if you choose), or `off` (no looking
until you ask). VS Code's own *Extensions: Auto Update* and *Auto Check
Updates* settings hold it back as they hold back the Marketplace's updates:
with Auto Update off a new version is offered rather than installed, and with
Auto Check Updates off the extension looks only when asked. The *Auto Update*
tick in the extension's gear menu is VS Code's, for extensions from the
Marketplace, and does not reach this one; the setting does.

## Using it

* **Open a file**: double-click it in the Explorer. If another extension also
  opens HDF5 files, VS Code asks which to use; *Open With…* on a file, or the
  `workbench.editorAssociations` setting, chooses.
* **Compare files**: select them in the Explorer, right-click, *Open Together
  in HDF5 Browser*. They open in one tab, where the ∩ and ∪ buttons combine
  their trees. *Add Files* in the tab adds more.
* **Drop files on a browser** — from the Explorer or from the Finder — and
  they go into it as more file tabs, as *Add Files* would add them. VS Code
  opens a dropped file as an editor in the group it is dropped on, so this
  goes for any HDF5 file opened into a group while a browser shows there: a
  double-click in the Explorer adds it to that browser too. A single click (a
  preview) and *Open Together* open a browser of their own, and so does a
  drop on the edge of a group, which VS Code opens beside it. Several files
  dropped at once go into one browser, also where none is open yet. For a
  browser of its own every time, turn `hdf5Browser.addToOpenBrowser` off.
* **Save**: *Download CSV*, *Download Excel*, the chart's right-click menu and
  *Export* in the preset manager open VS Code's Save dialog, starting in the
  folder of the file.
* A file that **changes on disk** — a run that has written new results — is
  read again when it has been left alone for a moment.
* **Light or dark**: the page follows VS Code's theme as it changes, unless you
  choose with the sun/moon toggle at the right of its header. The choice holds
  for every view and every session (the `hdf5Browser.theme` setting);
  toggling back to the mode VS Code is in goes back to following VS Code.
* The header is the file tabs alone, with *Add Files* and the toggle at its
  right end: the editor's own tab already names the file.
* **After an update**, reload the window: the extension offers *Reload
  Window* when it has installed one (or *Developer: Reload Window*). A view
  opened by the old copy, still running, says so at its top rather than half
  working.

## How a file is read

A file under 256 MB is read whole into the editor. A larger one is read the way
the web page reads a large file: a piece at a time, as it is looked at, so a
file of any size opens at once. Here the reading is done by the extension
itself, with the same HDF5 library (h5wasm) running in VS Code's extension
host, because a webview cannot read a file a piece at a time. In a remote
window (SSH, WSL, containers) the extension is meant to run where the file is,
so that only what is looked at crosses to your machine; that has not been
tested yet.

| Setting | |
|---|---|
| `hdf5Browser.readLazily` | `auto` (the default: 256 MB and up), `always`, or `never` (read whole, up to 1 GB) |
| `hdf5Browser.addToOpenBrowser` | `true` (the default): a file dropped on a browser, or opened into its group, goes into it; `false`: a browser of its own |
| `hdf5Browser.theme` | `auto` (the default: VS Code's theme), `light` or `dark`; the header's toggle sets it |
| `hdf5Browser.updates` | `install` (the default), `notify` or `off`: what a new version on kvotab.se leads to (see *Updates*) |

Data compressed with lzf, blosc, blosc2, bzip2, lz4, zstd, zfp, bitshuffle,
jpeg, bitgroom or bitround is decoded; the plugins are part of the extension.

## Privacy

The page makes no network requests: everything it needs is in the extension,
and its Content-Security-Policy lets nothing else load. It can reach only the
files it was opened with.

The extension's one request of its own is the look for an update: it fetches
`https://kvotab.se/rb-vscode/dist/latest.json`, and the package when there is
a newer version, as a browser fetches any of the site's files. Nothing about
the machine, the user or the files open is sent. `hdf5Browser.updates` set to
`off` stops it, except when *Check for Updates* is asked for.

## Limitations

* A file on a virtual file system (not on a disk the extension can reach) is
  always read whole, up to 1 GB.
* External links in a file are not followed (as on the web).
* Tested on macOS with VS Code 1.100 and 1.135. Windows, Linux and remote
  windows are not yet tested.

## Commands

| Command | |
|---|---|
| *Open Together in HDF5 Browser* | Explorer context menu, on one or more HDF5 files |
| *HDF5 Browser: Show Log* | What the extension and its pages have reported |
| *HDF5 Browser: Check for Updates* | Looks for a newer version on kvotab.se now; also in the extension's gear menu in the Extensions view |

## Building and testing

The extension is built from the site's files and is not edited by hand:

    cd rb-vscode
    npm install              # the packaging and test tools
    node build.mjs           # media/ and node/ from rb.html and resources/
    npx vsce package         # hdf5-browser-<version>.vsix

Install the `.vsix` with *Extensions: Install from VSIX…*. `build.mjs` checks
every bundled library against the hash the site pins, and refuses to build
when rb.html has changed in a way it does not expect. The tests are described
in `test/README.md`.

## Releasing

    # bump "version" in package.json (and add it to CHANGELOG.md), then
    node release.mjs         # build.mjs, vsce package, and dist/

`release.mjs` puts the package in `dist/hdf5-browser.vsix`, the one file name
the site links to, with `dist/latest.json` saying which version it is, how
big, its SHA-256, and the release's signature. Commit `dist/` and push: the VS
Code button on rb.html reads `latest.json` when its dialog opens, so the page
needs no change, and the copies installed (0.1.5 and later) find the new
version by themselves. A version is released once (`--force` to replace one):
a second build of the same version installed over the first leaves VS Code
running the old code over the new files until the window is reloaded. The
package is committed, so each release adds its size (about 4.5 MB) to the
repository's history.

The signature is made with the release key, an Ed25519 key that is never in
the repository: `~/.config/kvotab/hdf5-browser-release-key.pem`, or the file
`RB_VSCODE_RELEASE_KEY` names. The extension carries its public half,
`src/release-public-key.pem`, and `release.mjs` refuses to release without
the private half, or with one that does not match. Keep a copy of the key
somewhere safe (a password manager). Lost, it can be replaced
(`node release.mjs --replace-key`), but every copy installed before then
checks with the old key and has to be updated once by hand, from the site.

Licences of the bundled libraries: `THIRD-PARTY-NOTICES.md`.
