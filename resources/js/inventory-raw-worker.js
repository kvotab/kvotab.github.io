/* ==========================================================================
   CANISTER_INVENTORY.HTML: WRITING THE RAW DATA OFF THE PAGE

   The page posts a table (inventory-raw.js's form, its numbers handed over
   rather than copied) and what the file is to be; this writes the workbook
   or the CSV file and posts it back as a Blob, with how far it has come on
   the way. Millions of values take seconds, and the page goes on meanwhile.
   ========================================================================== */
/* global KVOT_INV_RAW */
'use strict';
importScripts('inventory-raw.js?v=20261102a');

self.onmessage = async (ev) => {
  const { format, table, about, head } = ev.data || {};
  try {
    const progress = (share) => self.postMessage({ share });
    const chunks = format === 'csv'
      ? KVOT_INV_RAW.csv(table, head, { progress })
      : await KVOT_INV_RAW.xlsx(table, about, { progress });
    const type = format === 'csv' ? 'text/csv;charset=utf-8' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    self.postMessage({ blob: new Blob(chunks, { type }) });
  } catch (err) {
    self.postMessage({ error: err && err.message ? err.message : String(err) });
  }
};
