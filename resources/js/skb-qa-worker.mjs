/*
  skb_qa_summary.html reads its workbooks here, several at once, so that a
  folder of large exports does not hold the page up. One message per
  workbook: { id, book }, answered with { id, result } or { id, error }.
*/
import { readBook, transferables } from './skb-qa-read.mjs?v=20261119';

self.onmessage = async (ev) => {
  const { id, book } = ev.data;
  try {
    const result = await readBook(book);
    self.postMessage({ id, result }, transferables(result));
  } catch (e) {
    self.postMessage({ id, error: String((e && e.message) || e) });
  }
};
