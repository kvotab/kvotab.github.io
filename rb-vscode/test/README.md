# Tests of the HDF5 Browser extension

Six, from the cheapest up. All but the first need `node build.mjs` first.

## test-update.mjs: what the updater installs, refuses and says

`src/update.js` against a site of its own (a local server whose release note
and package each case sets), with a stand-in for VS Code's API and a release
key made for the run. A newer version is installed only when its note is
signed with the release key over that version and the package's SHA-256, and
the package is that one: signed with another key, an older release's
signature on a newer version, no signature or no hash, a package changed or
longer than the note says are all refused, said once, and not sent to the
site to be fetched by hand. Also: up to date (an older, unsigned note too),
the three modes and VS Code's own Auto Update and Auto Check Updates, one
look for twelve hours across windows (and a clock put back), an offer left
open not holding up the command, a version another window installed (and one
VS Code is to remove), another window's lock (and a stale one), VS Code
refusing the install, a copy run from its folder, a note that is missing, not
JSON or unreachable, a VS Code too old, the key the extension carries, and
release.mjs refusing to release without the private key or with the wrong
one. 68 checks, a few seconds, no VS Code:

    node rb-vscode/test/test-update.mjs

## test-reader.py: the reader answers as the site's worker does

The page reads a large file through four questions (open, group, values,
close). On the site `resources/js/rb-lazy-worker.js` answers them; in VS Code
`src/reader.mjs` does, in the extension host. This asks both about every group
and every dataset of each file and compares the answers value for value and
type for type, after the worker's have gone through `src/codec.js` as the
reader's do. The files are the site's fixtures and one it makes with h5py of
what is awkward to carry: NaN, the infinities, -0, 64-bit integers past 2^53,
text that is not ASCII, soft, broken and external links, a compound, a 2-D and
an LZF dataset.

Needs the site's server and Chrome, as in `resources/tests/rb/README.md`:

    python3 rb-vscode/test/test-reader.py

When `rb-lazy-worker.js` changes, `build.mjs` refuses to build until this has
passed again and its new hash is in `READER_MIRRORS`.

## characterise-vscode.py: the page in VS Code is the page on the site

The site's characterisation walk (`resources/tests/rb/characterise.py`, its
seventeen steps) run inside a real VS Code, with the fixtures opened as a
reader opens them there. Compare with the site's `--open` fingerprints:

    python3 resources/tests/rb/characterise.py site-never --open never
    python3 rb-vscode/test/characterise-vscode.py vscode-never --open never
    python3 resources/tests/rb/compare.py site-never.json vscode-never.json

and the same with `always`, where the extension's reader reads the files.
Measured (VS Code 1.135), six fields differ in both, all in the first step,
the page's inventory before anything is loaded, and all expected:

| Field | Why |
|---|---|
| `dom.inventory/controlIds` | the site's map and navigation are not built in; VS Code adds `_defaultStyles` and `_vscodeApiScript` |
| `dom.inventory/inputs` | 47 to 42: the URL, Sample Data and VS Code buttons and the site's navigation and footer controls are not built in, and the light/dark toggle is added |
| `dom.inventory/treePlaceholder`, `hiddenAtStart`, `chartControlLabels` | a view exists only once a file is in it, so the inventory is taken with sample-a.h5 loaded |
| `_extension_log` | a field only this walk has: what the pages reported to the extension (empty) |

Anything else that moves is the extension showing something the site does
not. Between the extension's own two runs exactly the three fields the site's
README names differ (`load.two.files/lazy` and the two `memfs` counts).

## test-vscode.py: what only the extension does

Opening whole and lazily, past 2 GiB, compressed both ways, empty, dropped
into the page; Save through VS Code; Add Files; the preset dialog; the header
(no logo or name, every tab standing on its line, Add Files and the toggle at
the right, measured in px); VS Code's theme, and the light/dark toggle, kept in
`hdf5Browser.theme` and followed by every view; Open Together, same-named
files from two folders, a file rewritten on disk; the channel refusing
what the page was not given; and, last, the files rebuilt under the running
extension (as a .vsix of the same version installed over it does), after
which a new view must say to reload the window. 41 checks.

    python3 rb-vscode/test/test-vscode.py

Its steps that need a view of their own open the file with `own=True` (the
runner then opens it as the extension opens one for itself); where a file
opened into a showing browser goes is test-drop.py's.

## test-drop.py: a file dropped on a browser goes into it

VS Code keeps any drag out of a webview unless Shift is held, and opens a
dropped file as another editor in the group; the extension puts the file
into the browser that was showing there and closes that editor again
(`browserShowingBehind` in extension.js). With Shift the drop reaches the
page: files from the Finder the page reads itself, addresses from the
Explorer it passes to the extension. The test drops a file, then more (once
the stand-in editor was closed too soon and every later drop reached
nothing), two at once, the same file again, with Shift both kinds and a
name that is not HDF5, and checks that a preview, Open Together and the
setting off still open a browser of their own; last, three files dropped
where no browser is open, which must make one browser with the three in it
(VS Code opens a tab each and loads only the first), and a drop after it.
25 checks, on 1.100 and 1.135.

    python3 rb-vscode/test/test-drop.py

The drags are CDP's `Input.dispatchDragEvent` on the workbench's window,
coming in over the activity bar as a drag from outside does. CDP cannot carry
a drag from the workbench into the webview's frame, so a drop with Shift
starts over the page, which is what the page gets of a real one. Every drag
starts with a mouse move: that is what gives a webview its pointer events
back after the drag before, as a real pointer does.

## test-update.py: an installed copy updates itself

This folder, packaged, installed into a VS Code of its own as a download
from the site is; a server here plays the site, offering the next version
(this package with its version raised), signed with a key made for the run
(KVOT_HDF5_UPDATE_URL and KVOT_HDF5_UPDATE_KEY point the extension at them).
Twenty seconds after VS Code starts the copy installs it by itself and offers
the reload; *Reload Window*, clicked in the notification, starts the new
version, and VS Code marks the old one for removal; the new one does not look
again so soon; *Check for Updates* from the Command Palette says it is up to
date; and the extension's gear menu in the Extensions view has the command
(read where VS Code draws its menus in the window; 1.100, which has no
`window.menuStyle`, uses macOS's own, and that check is skipped). No
test/runner.js: a copy run from its folder is never updated. 16 checks on
1.135, 15 on 1.100.

    RB_VSCODE_EXE=... python3 rb-vscode/test/test-update.py

## Running VS Code for them

`vscode_driver.py` starts a VS Code of its own for each run: a separate build
(`RB_VSCODE_EXE`, or downloaded by `@vscode/test-electron` after `npm install`;
`RB_VSCODE_VERSION` picks the version, 1.135.0 by default), a fresh profile in
a temporary folder, its own extensions and shared-data folders, updates off.
Its window appears while the test runs. The extension is loaded from this
folder in development mode, and `runner.js` is run inside it by VS Code
(`--extensionTestsPath`), which lets the test open files, answer the Save and
open dialogs, and change settings. The page is driven over the DevTools
protocol, with the same `ev()` as the site's tests.

What `vscode_driver.py` works around is listed at its top; each cost a run to
find.
