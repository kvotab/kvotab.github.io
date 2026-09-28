# Third-party notices

The HDF5 Browser extension is written by Kvot AB and published under the MIT
licence (see `LICENSE`). Unlike the page on kvotab.se, which has the visitor's
browser fetch these libraries from their publishers, the extension carries
copies of them, so it carries their licences too: every text is in
`licenses/`, and `licenses/MANIFEST.json` says where each came from.

## In the page (`media/vendor/`)

| Component | Version | Licence | Text |
|---|---|---|---|
| [Plotly.js](https://github.com/plotly/plotly.js) | 2.27.0 | MIT | `licenses/plotly.js-2.27.0/` |
| [SortableJS](https://github.com/SortableJS/Sortable) | 1.15.0 | MIT | `licenses/sortablejs-1.15.0/` |
| [JSZip](https://github.com/Stuk/jszip) | 3.10.1 | MIT or GPLv3; used under MIT | `licenses/jszip-3.10.1/` |
| [h5wasm](https://github.com/usnistgov/h5wasm), with the [HDF5](https://www.hdfgroup.org/solutions/hdf5/) library compiled in | 0.10.3 (HDF5 2.0.0) | NIST software notice; HDF5's BSD-style licence | `licenses/h5wasm-0.10.3/` |
| [h5wasm-plugins](https://github.com/h5wasm/h5wasm-plugins) (the eleven `.so` compression plugins) | 0.3.0 | ISC by its package.json, Apache-2.0 by its LICENSE file; The HDF Group's COPYING | `licenses/h5wasm-plugins-0.3.0/` |

The plugins are compiled from The HDF Group's
[hdf5_plugins](https://github.com/HDFGroup/hdf5_plugins) (`licenses/hdf5_plugins/`:
its COPYING and each filter's own legal files) and the compression libraries it
builds against, each under its own licence:

| Library | Version | Licence | Text |
|---|---|---|---|
| [c-blosc](https://github.com/Blosc/c-blosc), with the codecs it compiles in | 1.21.6 | BSD-3-Clause (and those of its `LICENSES/`) | `licenses/c-blosc-1.21.6/` |
| [c-blosc2](https://github.com/Blosc/c-blosc2), likewise | 2.17.1 | BSD-3-Clause (and those of its `LICENSES/`) | `licenses/c-blosc2-2.17.1/` |
| [zlib](https://zlib.net/) | 1.3.1 | zlib | `licenses/zlib-1.3.1/` |
| [Zstandard](https://github.com/facebook/zstd) | 1.5.7 | BSD-3-Clause (or GPLv2; used under BSD) | `licenses/zstd-1.5.7/` |
| [LZ4](https://github.com/lz4/lz4) | 1.10.0 | BSD-2-Clause | `licenses/lz4-1.10.0/` |
| [zfp](https://github.com/LLNL/zfp) | 1.0.1 | BSD-3-Clause | `licenses/zfp-1.0.1/` |
| [bitshuffle](https://github.com/kiyo-masui/bitshuffle) | 0.5.2 | MIT | `licenses/bitshuffle-0.5.2/` |
| [bzip2](https://sourceware.org/bzip2/) | 1.0.8 | bzip2 licence (BSD-style) | `licenses/bzip2-1.0.8/` |
| [liblzf](http://software.schmorp.de/pkg/liblzf.html) | 3.6 | BSD-2-Clause | `licenses/liblzf-3.6/` |
| [libjpeg](https://www.ijg.org/) (IJG) | 9e | IJG licence (README, LEGAL ISSUES) | `licenses/libjpeg-9e/` |

The versions are the ones hdf5_plugins names in its build presets. This
software is based in part on the work of the Independent JPEG Group.

## In the extension host (`node/h5wasm/`)

h5wasm's Node build, the same h5wasm 0.10.3 as above (`licenses/h5wasm-0.10.3/`).
The extension host's reader uses the page's plugin files, from `media/vendor/`.

## Fonts

| Font | Licence | Text |
|---|---|---|
| Rawengulk Sans | SIL Open Font License 1.1 | `licenses/rawengulk-sans/` |

## Work followed, not copied

The [H5Web extension](https://github.com/silx-kit/vscode-h5web) by the ESRF
(MIT) showed that h5wasm in a VS Code webview works, and how it hands the
extension a file to save. No code of it is used.
