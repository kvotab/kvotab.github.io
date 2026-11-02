/* ==========================================================================
   SMUI.HTML: MATLAB MAT-FILES

   A MAT-file, in any of the formats MATLAB saves (-v4, -v6, -v7 and -v7.3),
   opens in the Open dialog as the Data Browser (rb.html) shows it. That
   page's reader, rb-mat.js, reads the variables into its tree of groups and
   datasets: an array in MATLAB's own size, char as text, a cell -- or a
   struct array's field -- that reads as a table as one dataset, a table's
   variables by name, another object's saved properties. Here the tree is
   written with h5wasm as an HDF5 file in the worker's memory, and
   smui-hdf5-read.js reads that file as it reads any other. Each dataset
   carries MATLAB_size, which tells the reader it is in MATLAB's shape
   already: a -v7.3 file's own arrays, read without this file, are stored
   the other way round.

   The HDF5 worker loads this file, after kvot-safe.js and rb-mat.js, when
   the first MAT-file comes; hdf5-read.mjs loads the same three for the
   tests. Nothing here touches the page.

     SM.mat.write(h5wasm, buffer, path, { fileName, onProgress })
         the MAT-file's bytes read, and written as an HDF5 file at path:
         { format, header, variables, unread }
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});

  /* What rb-mat.js asks of the Data Browser's page, given as that page has
     it: rb-eas.js's groups and link names, rb-utils.js's escaping and its
     wait for h5wasm, rb-init.js's check of the HDF5 signature. The size
     limit and the byte counts are kvot-safe.js's, as on that page. rb-mat.js
     finds h5wasm as window.h5wasm: here a window that holds only that. */
  root.easGroup = (attrs = {}) => ({ kind: 'group', attrs, children: new Map() });
  root.easLinkName = (s) => {
    const out = String(s ?? '').replace(/\//g, '⁄').trim();
    return out === '' || out === '.' || out === '..' ? '_' : out;
  };
  root.escapeHtml = (text) => kvotEscapeHtml(text);
  root.validateHdf5Buffer = (buffer) => ({ ok: SM.h5.sniff(new Uint8Array(buffer, 0, Math.min(buffer.byteLength, 65544))) === 'hdf5' });
  root.ignoreFailure = () => {};
  if (typeof root.window === 'undefined') root.window = { get h5wasm() { return root.h5wasm; } };
  root.waitForH5Wasm = async () => root.window.h5wasm;

  /* Attributes as rb-eas.js writes them: a number as a double, a list as
     strings, anything else as its text. */
  function setAttrs(obj, attrs) {
    for (const [name, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null) continue;
      if (typeof value === 'number') { if (Number.isFinite(value)) obj.create_attribute(name, value, [], '<d'); }
      else if (Array.isArray(value)) { if (value.length) obj.create_attribute(name, value.map(String)); }
      else obj.create_attribute(name, String(value));
    }
  }

  async function write(h5wasm, buffer, path, { fileName = 'file.mat', onProgress = null } = {}) {
    if (!buffer || !buffer.byteLength) throw new Error('the file is empty');
    if (buffer.byteLength > KVOT_FILE_SIZE_LIMITS.dataset) throw new Error(`it is ${kvotFormatBytes(buffer.byteLength)}, more than this page reads whole`);
    if (onProgress) onProgress(0, 0, `Reading the variables of ${fileName}`);
    let mat = await readMatFile(buffer);
    // (what was read holds copies: the file's bytes can go)
    buffer = null;
    if (!mat.variables.length) throw new Error('it holds no variables');
    if (mat.variables.every((v) => v.error)) throw new Error(mat.variables[0].error);
    const out = { format: mat.format, header: mat.header, variables: mat.variables.length, unread: mat.variables.filter((v) => v.error).length };
    const { tree, datasets } = matTree(fileName, mat);
    // the arrays as read are held by the tree alone now, and each goes as
    // it is written
    mat = null;
    const f = new h5wasm.File(path, 'w');
    let done = 0;
    try {
      setAttrs(f, tree.attrs);
      const walk = (into, node) => {
        for (const [name, child] of node.children) {
          if (child.kind === 'group') {
            const g = into.create_group(name);
            setAttrs(g, child.attrs);
            walk(g, child);
            continue;
          }
          const ds = into.create_dataset({ name, data: child.make(), shape: child.shape, dtype: child.dtype });
          setAttrs(ds, child.attrs);
          child.make = null;
          if (++done % 100 === 0 && onProgress) onProgress(done, datasets, `Reading ${fileName}: ${done.toLocaleString('en-US')} of ${datasets.toLocaleString('en-US')} arrays`);
        }
      };
      walk(f, tree);
    } finally {
      f.close();
    }
    return out;
  }

  SM.mat = Object.freeze({ write });
}(typeof self !== 'undefined' ? self : this));
