/*
  Decay data made in this browser from a release of ENSDF a visitor opened
  (ensdf-make-worker.js), kept in IndexedDB: the page's calculation workers
  read them from there, and a release is made once, not at every visit.

    database 'kvot-dose-decay'
      folders  {key, label, version, made, nuclides, source}
      files    {key: the folder's key + '\n' + path, text}

  A folder holds what scripts/gen-dose-ensdf.mjs writes for the site:
  decay/index.json, decay/<El>.json and notes.json. Its key is the key under
  which ensdf-sources.js keeps the release's files ('kvot-ensdf'), shared
  with the Chart of Nuclides and Radionuclide Decay Chains.

  Works on the page and in workers alike.
*/
const NAME = 'kvot-dose-decay';

/* What ensdf-make.js makes carries this stamp; a folder of another is made
   again from its release. Change it whenever the making changes. */
export const MAKE_VERSION = '2026-10-06';
let opening = null;

function open() {
  return (opening ||= new Promise((resolve, reject) => {
    let req;
    try { req = indexedDB.open(NAME, 1); } catch (e) { reject(e); return; }
    req.onupgradeneeded = () => {
      req.result.createObjectStore('folders', { keyPath: 'key' });
      req.result.createObjectStore('files', { keyPath: 'key' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error('IndexedDB unavailable'));
  }).catch((e) => { opening = null; throw e; }));
}

function tx(stores, mode, fn) {
  return open().then((db) => new Promise((resolve, reject) => {
    const t = db.transaction(stores, mode);
    const out = fn(t);
    t.oncomplete = () => resolve(out && 'result' in out ? out.result : out);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error || new Error('aborted'));
  }));
}
const fileKey = (key, path) => `${key}\n${path}`;
const ofFolder = (key) => IDBKeyRange.bound(`${key}\n`, `${key}\n￿`);

/** Every folder kept: [{key, label, version, made, nuclides, source}]. */
export const listFolders = () => tx(['folders'], 'readonly', (t) => t.objectStore('folders').getAll());

/** One folder's record, or undefined. */
export const folderInfo = (key) => tx(['folders'], 'readonly', (t) => t.objectStore('folders').get(key));

/**
 * Keep a folder, replacing one of the same key.
 * @param {string} key
 * @param {object} meta  {label, version, nuclides, source}
 * @param {Map<string, string>} files  path -> text
 */
export function writeFolder(key, meta, files) {
  return tx(['folders', 'files'], 'readwrite', (t) => {
    const fs = t.objectStore('files');
    fs.delete(ofFolder(key));
    for (const [path, text] of files) fs.put({ key: fileKey(key, path), text });
    t.objectStore('folders').put({ ...meta, key, made: Date.now() });
  });
}

/** A file of a folder as text, or undefined. */
export const readFile = (key, path) => tx(['files'], 'readonly', (t) => t.objectStore('files').get(fileKey(key, path)))
  .then((r) => r?.text);

/** Forget a folder and its files. */
export const removeFolder = (key) => tx(['folders', 'files'], 'readwrite', (t) => {
  t.objectStore('files').delete(ofFolder(key));
  t.objectStore('folders').delete(key);
});

/** An io (data.js) for a folder: json(path). */
export function storeIO(key) {
  return {
    async json(path) {
      const text = await readFile(key, path);
      if (text == null) throw new Error(`${path}: these decay data are not kept in this browser; open the release again`);
      return JSON.parse(text);
    },
  };
}
