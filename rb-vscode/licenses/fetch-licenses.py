#!/usr/bin/env python3
"""Fetch the licence texts of what the extension bundles into this folder.

The site loads its libraries from their publishers' CDNs; the extension
carries copies of them (media/vendor/, node/h5wasm/), so it must carry their
licences too. The compression plugins are compiled from The HDF Group's
hdf5_plugins, which fetches each compression library at build time, so their
notices come from those libraries' own releases -- the versions hdf5_plugins
names in its CMakePresets.json.

    python3 rb-vscode/licenses/fetch-licenses.py

Writes one folder per component and MANIFEST.json (where each file came
from, and its SHA-256). The files are committed; run this again only when a
bundled version changes, and read the diff.
"""
import hashlib
import io
import json
import os
import ssl
import subprocess
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
HDF5_PLUGINS = 'https://raw.githubusercontent.com/HDFGroup/hdf5_plugins/bafec5a3bf14c96371c99cc02019f3722912038e/'
JSDELIVR = 'https://cdn.jsdelivr.net/npm/'
GITHUB = 'https://raw.githubusercontent.com/'

FILES = [
    # The page's libraries.
    ('plotly.js-2.27.0', 'LICENSE', JSDELIVR + 'plotly.js-dist-min@2.27.0/LICENSE'),
    ('sortablejs-1.15.0', 'LICENSE', JSDELIVR + 'sortablejs@1.15.0/LICENSE'),
    ('jszip-3.10.1', 'LICENSE.markdown', JSDELIVR + 'jszip@3.10.1/LICENSE.markdown'),
    # h5wasm, with the HDF5 library compiled into it (its LICENSE.txt has both).
    ('h5wasm-0.10.3', 'LICENSE.txt', JSDELIVR + 'h5wasm@0.10.3/LICENSE.txt'),
    # The plugins package, and the plugin sources it is built from.
    ('h5wasm-plugins-0.3.0', 'LICENSE', JSDELIVR + 'h5wasm-plugins@0.3.0/LICENSE'),
    ('h5wasm-plugins-0.3.0', 'COPYING', JSDELIVR + 'h5wasm-plugins@0.3.0/COPYING'),
    ('hdf5_plugins', 'COPYING', HDF5_PLUGINS + 'COPYING'),
    ('hdf5_plugins', 'BITGROOM-LICENSE', HDF5_PLUGINS + 'BITGROOM/Additional_Legal/LICENSE'),
    ('hdf5_plugins', 'BITROUND-LICENSE', HDF5_PLUGINS + 'BITROUND/Additional_Legal/LICENSE'),
    ('hdf5_plugins', 'BSHUF-LICENSE', HDF5_PLUGINS + 'BSHUF/Additional_Legal/LICENSE'),
    ('hdf5_plugins', 'LZ4-LICENSE', HDF5_PLUGINS + 'LZ4/Additional_Legal/LICENSE'),
    ('hdf5_plugins', 'ZSTD-LICENSE', HDF5_PLUGINS + 'ZSTD/Additional_Legal/LICENSE'),
    ('hdf5_plugins', 'ZFP-LICENSE', HDF5_PLUGINS + 'ZFP/LICENSE'),
    ('hdf5_plugins', 'PyTables_Copyrights_and_Licenses.txt', HDF5_PLUGINS + 'BLOSC/Additional_Legal/PyTables_Copyrights_and_Licenses.txt'),
    ('hdf5_plugins', 'h5py_Copyrights_and_Licenses.txt', HDF5_PLUGINS + 'LZF/Additional_Legal/h5py_Copyrights_and_Licenses.txt'),
    # The compression libraries, at the versions hdf5_plugins builds.
    ('c-blosc-1.21.6', 'LICENSE.txt', GITHUB + 'Blosc/c-blosc/v1.21.6/LICENSE.txt'),
    ('c-blosc2-2.17.1', 'LICENSE.txt', GITHUB + 'Blosc/c-blosc2/v2.17.1/LICENSE.txt'),
    ('zlib-1.3.1', 'LICENSE', GITHUB + 'madler/zlib/v1.3.1/LICENSE'),
    ('zstd-1.5.7', 'LICENSE', GITHUB + 'facebook/zstd/v1.5.7/LICENSE'),
    ('lz4-1.10.0', 'LICENSE', GITHUB + 'lz4/lz4/v1.10.0/lib/LICENSE'),
    ('zfp-1.0.1', 'LICENSE', GITHUB + 'LLNL/zfp/1.0.1/LICENSE'),
    ('bitshuffle-0.5.2', 'LICENSE', GITHUB + 'kiyo-masui/bitshuffle/0.5.2/LICENSE'),
    ('bzip2-1.0.8', 'LICENSE', 'https://gitlab.com/bzip2/bzip2/-/raw/bzip2-1.0.8/LICENSE'),
]

# Licences that come only inside a source tarball: (folder, name, tarball, member).
TARBALLS = [
    ('libjpeg-9e', 'README', 'https://www.ijg.org/files/jpegsrc.v9e.tar.gz', 'jpeg-9e/README'),
    ('liblzf-3.6', 'LICENSE', 'http://dist.schmorp.de/liblzf/liblzf-3.6.tar.gz', 'liblzf-3.6/LICENSE'),
]

# c-blosc and c-blosc2 carry the licences of what they compile in, in LICENSES/.
BLOSC_LICENSES = [('c-blosc-1.21.6', 'Blosc/c-blosc', 'v1.21.6'), ('c-blosc2-2.17.1', 'Blosc/c-blosc2', 'v2.17.1')]


def get(url):
    # A python.org Python has no certificates until its Install Certificates
    # script is run; certifi's, when it is installed, or curl's otherwise.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return subprocess.run(['curl', '-sSfL', '--max-time', '60', url], check=True, capture_output=True).stdout
    req = urllib.request.Request(url, headers={'User-Agent': 'kvotab-licence-fetch'})
    with urllib.request.urlopen(req, timeout=60, context=context) as r:
        return r.read()


def main():
    manifest = []

    def keep(folder, name, data, source):
        os.makedirs(os.path.join(HERE, folder), exist_ok=True)
        with open(os.path.join(HERE, folder, name), 'wb') as fh:
            fh.write(data)
        manifest.append({'file': f'{folder}/{name}', 'source': source, 'sha256': hashlib.sha256(data).hexdigest()})
        print(f'  {folder}/{name}  ({len(data)} bytes)')

    for folder, name, url in FILES:
        keep(folder, name, get(url), url)
    for folder, repo, tag in BLOSC_LICENSES:
        listing = json.loads(get(f'https://api.github.com/repos/{repo}/contents/LICENSES?ref={tag}'))
        for entry in listing:
            if entry['type'] == 'file':
                keep(folder, 'LICENSES-' + entry['name'], get(entry['download_url']), entry['download_url'])
    for folder, name, url, member in TARBALLS:
        with tarfile.open(fileobj=io.BytesIO(get(url)), mode='r:gz') as tar:
            keep(folder, name, tar.extractfile(member).read(), f'{url} ({member})')
    with open(os.path.join(REPO, 'vendors', 'font', 'SIL Open Font License.txt'), 'rb') as fh:
        keep('rawengulk-sans', 'SIL Open Font License.txt', fh.read(), 'vendors/font/SIL Open Font License.txt in this repository')

    with open(os.path.join(HERE, 'MANIFEST.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    print(f'{len(manifest)} files')


if __name__ == '__main__':
    main()
