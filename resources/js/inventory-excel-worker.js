/* ==========================================================================
   CANISTER_INVENTORY.HTML: WRITING AN EXCEL FILE OFF THE PAGE

   The page posts the sheets (inventory-excel.js's form); this writes the
   workbook with SheetJS and posts the file back, handed over rather than
   copied. A sheet of every element and nuclide takes seconds to write, and
   the page goes on meanwhile.
   ========================================================================== */
/* global XLSX, KVOT_INV_EXCEL */
'use strict';
importScripts('../../vendors/js/xlsx-0.20.3.full.min.js?v=20261009', 'inventory-excel.js?v=20261102b');

self.onmessage = (ev) => {
  try {
    const buf = KVOT_INV_EXCEL.build(XLSX, (ev.data || {}).sheets || []);
    self.postMessage({ buf }, [buf]);
  } catch (err) {
    self.postMessage({ error: err && err.message ? err.message : String(err) });
  }
};
