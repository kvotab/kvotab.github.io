/* ==========================================================================
   CANISTER_INVENTORY.HTML: READING AN INVENTORY OFF THE PAGE

   The page posts a File, with the zip entry to read if the inventory is in
   an archive, or gzip: true for a gzip file; this reads it a slice at a time
   with inventory-json.js (unpacking as it goes) and posts back its progress,
   then the columns and the amounts, handed over rather than copied. A
   message {stop: true} stops it between slices.
   ========================================================================== */
/* global KVOT_INV_JSON */
'use strict';
importScripts('inventory-json.js?v=20261102b');

let stopped = false;

self.onmessage = async (ev) => {
  const msg = ev.data || {};
  if (msg.stop) { stopped = true; return; }
  if (!msg.file) return;
  stopped = false;
  const J = KVOT_INV_JSON;
  let last = 0;
  const report = (share) => {
    const now = Date.now();
    if (now - last > 100 || share >= 1) { last = now; self.postMessage({ progress: share }); }
  };
  try {
    let data;
    if (msg.entry || msg.gzip) {
      /* Progress by the packed bytes read: the unpacked size of a gzip file is not known. */
      const total = msg.entry ? msg.entry.csize : msg.file.size;
      let seen = 0;
      const onBytes = (n) => { seen += n; report(total ? Math.min(1, seen / total) : 0); };
      const stream = msg.entry ? await J.zipEntryStream(msg.file, msg.entry, onBytes) : J.unpack(msg.file, 'gzip', onBytes);
      data = await J.readInventoryStream(stream, { shouldStop: () => stopped });
    } else {
      data = await J.readInventory(J.blobSource(msg.file), report, { shouldStop: () => stopped });
    }
    self.postMessage({ data }, J.transferables(data));
  } catch (err) {
    self.postMessage({ error: err && err.message ? err.message : String(err) });
  }
};
