/* ==========================================================================
   16. IN-MEMORY FILE HANDOFF

   Two ways for another page to open an HDF5 file here without the user ever
   saving it to disk. Both end at ingestHdf5Buffer(), the same entry point the
   file picker uses, so a handed-over file behaves exactly like a dropped one.

   ── 1. postMessage (works cross-origin, transfers the bytes zero-copy) ──

     // In the producing page, inside a click handler — popup blockers
     // require the user gesture.
     const win = window.open('https://kvotab.se/rb.html#handoff=' +
                             encodeURIComponent(location.origin), '_blank');

     addEventListener('message', function onMsg(e) {
       if (e.origin !== 'https://kvotab.se') return;
       if (e.data && e.data.kvot === 'rb-ready') {
         // buffer is an ArrayBuffer holding the .h5 bytes
         win.postMessage({ kvot: 'rb-open', name: 'results.h5', buffer },
                         'https://kvotab.se', [buffer]);
       }
       if (e.data && e.data.kvot === 'rb-opened') {
         removeEventListener('message', onMsg);   // done
       }
       if (e.data && e.data.kvot === 'rb-error') {
         removeEventListener('message', onMsg);
         console.error('HDF5 Browser refused the file:', e.data.message);
       }
     });

   Several files at once: send { kvot: 'rb-open', files: [{name, buffer}, …] }
   and list every buffer in the transfer array.

   While the producing page is still building its data it can say so, as often
   as it likes, and the waiting tab will show it:

     win.postMessage({ kvot: 'rb-progress', text: 'Running realisations',
                       loaded: 40, total: 100 }, 'https://kvotab.se');

   Both loaded and total are optional; with neither, the text alone is shown.

   The handshake exists because the new tab is not listening when window.open()
   returns — rb.html announces itself with 'rb-ready' once it is, and keeps
   repeating that until something arrives. The repeat is what makes it safe to
   take your time building the data, but attach the listener BEFORE starting
   that work, and ignore every 'rb-ready' after the first: the buffer is
   transferred by the first send and is empty afterwards.

   ── 2. ?url= (same origin, cheapest) ──

     const url = URL.createObjectURL(blob);            // blob: URL
     location.href = 'rb.html?url=' + encodeURIComponent(url);

   A blob: URL resolves only within the origin that created it and only while
   the creating document is alive, so this suits a same-origin producer that
   stays open. Plain https: URLs work here too.

   ── What is accepted ──

   Only origins in RB_HANDOFF_ALLOWED_ORIGINS, only when the page was opened
   with a #handoff hash, only bytes that pass the HDF5 signature check, and
   only up to the same size limit the file picker enforces.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why
/**
 * Origins allowed to push files into this page.
 *
 * Add a producing page's origin here to let it hand files over; an origin that
 * is not listed gets nothing but the content-free ready ping. Never use '*':
 * any page holding a reference to this tab could then replace what the user is
 * looking at. Origins are compared as scheme + host + port with no trailing
 * slash, and localhost and 127.0.0.1 are different origins — list whichever
 * one the producer is actually served from.
 *
 * @type {string[]}
 */
const RB_HANDOFF_ALLOWED_ORIGINS = [
  window.location.origin,
  'http://localhost:8080'
];

/** Largest handoff accepted, matching the file picker's limit. */
const RB_HANDOFF_MAX_BYTES = KVOT_FILE_SIZE_LIMITS.dataset;

/*
  How long the tab sits quiet before it says more about the wait. The first
  step reassures, the second admits nothing is coming — a spinner that never
  resolves is worse than an answer.
*/
const HANDOFF_WAIT_HINT_MS = 20000;
const HANDOFF_WAIT_GIVEUP_MS = 90000;

/*
  Readiness is announced repeatedly, not once.

  A producer that spends time building its data before it starts listening
  would miss a single announcement and then wait forever for a tab that was
  ready all along — the slower the producer, the more certain the failure.
  Repeating costs nothing and removes the race.
*/
const HANDOFF_READY_PING_MS = 1000;

/** Timers for the waiting state, cleared as soon as anything arrives. */
let _handoffWaitTimers = [];
/** Interval announcing readiness, stopped when anything arrives. */
let _handoffReadyPinger = null;
/** The tree's own placeholder text, put back if nothing is ever sent. */
let _handoffTreePlaceholder = null;

/**
 * Say that this tab is open and waiting, from the moment it loads.
 *
 * Without this the tab is silent for as long as the producing page needs to
 * build its data — which is exactly the stretch where a person wonders
 * whether anything is happening at all.
 *
 * @returns {void}
 */
function beginHandoffWait() {
  setFileLoadProgress(0, 'Waiting for the other page…');

  const tree = document.getElementById('tree');
  if (tree && tree.classList.contains('loading')) {
    _handoffTreePlaceholder = tree.textContent;
    tree.textContent = 'Waiting for the other page to send a file…';
  }

  _handoffWaitTimers.push(setTimeout(() => {
    setFileLoadProgress(null, 'Still waiting for the other page…');
  }, HANDOFF_WAIT_HINT_MS));

  _handoffWaitTimers.push(setTimeout(() => {
    endHandoffWait();
    hideFileLoadTicker();
    const treeEl = document.getElementById('tree');
    if (treeEl && _handoffTreePlaceholder && treeEl.classList.contains('loading')) {
      treeEl.textContent = _handoffTreePlaceholder;
    }
    kvotTrace('[handoff] Nothing arrived — stopped waiting.');
  }, HANDOFF_WAIT_GIVEUP_MS));
}

/**
 * Stop the waiting timers. Leaves the ticker alone: by the time this runs the
 * receiving flow is usually driving it.
 *
 * @returns {void}
 */
function endHandoffWait() {
  _handoffWaitTimers.forEach(clearTimeout);
  _handoffWaitTimers = [];
  if (_handoffReadyPinger !== null) {
    clearInterval(_handoffReadyPinger);
    _handoffReadyPinger = null;
  }
}

/**
 * Show progress the producing page reported about its own work.
 * Its message may carry text, or loaded/total counts, or both.
 *
 * @param {Object} data - An 'rb-progress' message
 * @returns {void}
 */
function showProducerProgress(data) {
  const loaded = Number(data.loaded);
  const total = Number(data.total);
  const measured = isFinite(loaded) && isFinite(total) && total > 0;
  const text = typeof data.text === 'string' && data.text.trim()
    ? data.text.trim().slice(0, 120)
    : 'The other page is preparing the file…';

  setFileLoadProgress(measured ? loaded / total : null,
                      measured ? `${text} — ${Math.round((loaded / total) * 100)}%` : text);
}

/**
 * Read the #handoff hash.
 * Accepts '#handoff' and '#handoff=<producer origin>'; the origin form lets
 * the ready ping be addressed rather than broadcast.
 *
 * @returns {{active: boolean, declaredOrigin: string|null}}
 */
function readHandoffHash() {
  const hash = String(window.location.hash || '');
  const match = hash.match(/^#handoff(?:=(.*))?$/);
  if (!match) return { active: false, declaredOrigin: null };

  let declaredOrigin = null;
  if (match[1]) {
    try {
      declaredOrigin = new URL(decodeURIComponent(match[1])).origin;
    } catch (_) {
      declaredOrigin = null;
    }
  }
  return { active: true, declaredOrigin };
}

/**
 * Whether an origin may hand files to this page.
 * @param {string} origin
 * @returns {boolean}
 */
function isHandoffOriginAllowed(origin) {
  return !!origin && origin !== 'null' && RB_HANDOFF_ALLOWED_ORIGINS.includes(origin);
}

/**
 * Make a sender-supplied name safe to use as a file key.
 * Names are escaped before they reach the DOM, so this is about keeping keys
 * sane rather than about injection: no path separators, no control characters,
 * bounded length, and an HDF5 extension.
 *
 * @param {*} name
 * @param {number} [index] - Position in a multi-file handoff, for the fallback name
 * @returns {string}
 */
function sanitizeHandoffName(name, index = 0) {
  let clean = String(name == null ? '' : name)
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .replace(/[\\/]/g, '_')
    .trim();
  if (!clean || clean === '.' || clean === '..') {
    clean = index > 0 ? `handoff-${index + 1}.h5` : 'handoff.h5';
  }
  if (clean.length > 120) clean = clean.slice(0, 120);
  if (!/\.(h5|hdf5|he5)$/i.test(clean)) clean += '.h5';
  return clean;
}

/**
 * Coerce whatever the sender put in the payload into an ArrayBuffer.
 * ArrayBuffer, any typed-array view and Blob are all accepted; a view is
 * copied only when it is a window onto part of a larger buffer.
 *
 * @param {ArrayBuffer|ArrayBufferView|Blob} payload
 * @returns {Promise<ArrayBuffer|null>}
 */
async function handoffPayloadToBuffer(payload) {
  if (!payload) return null;
  if (payload instanceof ArrayBuffer) return payload;
  if (ArrayBuffer.isView(payload)) {
    return payload.byteOffset === 0 && payload.byteLength === payload.buffer.byteLength
      ? payload.buffer
      : payload.buffer.slice(payload.byteOffset, payload.byteOffset + payload.byteLength);
  }
  if (typeof Blob !== 'undefined' && payload instanceof Blob) {
    return await payload.arrayBuffer();
  }
  return null;
}

/**
 * Normalise an 'rb-open' message into a list of {name, payload} entries.
 * @param {Object} data
 * @returns {Array<{name: *, payload: *}>}
 */
function handoffEntriesFromMessage(data) {
  if (Array.isArray(data.files)) {
    return data.files
      .filter(Boolean)
      .map(f => ({ name: f.name, payload: f.buffer || f.data || f.blob }));
  }
  return [{ name: data.name, payload: data.buffer || data.data || data.blob }];
}

/**
 * Handle an 'rb-open' message: mount every file it carries, refresh the tree,
 * and report back to the sender.
 *
 * @param {MessageEvent} event
 * @returns {Promise<void>}
 */
async function receiveHandoffMessage(event) {
  const data = event.data;
  const entries = handoffEntriesFromMessage(data);
  const loaded = [];

  /*
    Progress is reported per file and then per phase within a file. One big
    file is the common case, and for it the phases are what move: reading the
    payload, mounting it, then rebuilding the tree.
  */
  const phase = (index, text) => setFileLoadProgress(
    entries.length > 1 ? index / entries.length : null,
    entries.length > 1 ? `${index + 1}/${entries.length} — ${text}` : text);

  setFileLoadProgress(0, 'Receiving…');
  await yieldForPaint();

  try {
    for (let i = 0; i < entries.length; i++) {
      const fileName = sanitizeHandoffName(entries[i].name, i);
      phase(i, `Receiving ${fileName}…`);

      const buffer = await handoffPayloadToBuffer(entries[i].payload);
      if (!buffer) throw new Error(`${fileName}: no ArrayBuffer, typed array or Blob in the message.`);
      if (buffer.byteLength > RB_HANDOFF_MAX_BYTES) {
        throw new Error(`${fileName}: ${kvotFormatBytes(buffer.byteLength)} exceeds the `
                        + `${kvotFormatBytes(RB_HANDOFF_MAX_BYTES)} handoff limit.`);
      }

      phase(i, `Opening ${fileName} (${kvotFormatBytes(buffer.byteLength)})…`);
      await ingestHdf5Buffer(fileName, buffer, 'receiveHandoffMessage');
      loaded.push(fileName);
    }

    try { await ensureTreeWorkerReady(5000); } catch (_) { ignoreFailure('receiveHandoffMessage', _); }
    setFileLoadProgress(1, 'Refreshing tree…');
    await updateTabs(true);
    hideFileLoadTicker();

    replyToHandoff(event, { kvot: 'rb-opened', names: loaded });
    kvotTrace('[handoff] Opened', loaded.join(', '), 'from', event.origin);
  } catch (err) {
    hideFileLoadTicker();
    replyToHandoff(event, { kvot: 'rb-error', message: err.message || String(err) });
    reportFailure('handoff:receive', err, {
      userMessage: 'The file handed over by the other page could not be opened.'
    });
  }
}

/**
 * Reply on the same channel the message arrived on, addressed to its origin.
 * @param {MessageEvent} event
 * @param {Object} message
 * @returns {void}
 */
function replyToHandoff(event, message) {
  try {
    if (event.source) event.source.postMessage(message, event.origin);
  } catch (e) {
    ignoreFailure('replyToHandoff', e);
  }
}

/**
 * Announce readiness to whoever opened this tab, and listen for files.
 * Does nothing unless the page was opened with a #handoff hash.
 *
 * @returns {void}
 */
function initHandoffReceiver() {
  const { active, declaredOrigin } = readHandoffHash();
  if (!active) return;

  window.addEventListener('message', (event) => {
    if (!event.data || typeof event.data !== 'object') return;
    const kind = event.data.kvot;
    if (kind !== 'rb-open' && kind !== 'rb-progress') return;

    if (!isHandoffOriginAllowed(event.origin)) {
      kvotWarn('[handoff] Ignored a message from', event.origin,
                   '— add it to RB_HANDOFF_ALLOWED_ORIGINS to allow it.');
      return;
    }
    if (declaredOrigin && event.origin !== declaredOrigin) {
      kvotWarn('[handoff] Ignored a message from', event.origin,
                   '— the link declared', declaredOrigin);
      return;
    }

    /*
      A progress report means the sender is alive and working, so the waiting
      timers stop here too — otherwise a slow producer would be declared absent
      while it was visibly still going.
    */
    endHandoffWait();

    if (kind === 'rb-progress') {
      showProducerProgress(event.data);
      return;
    }

    receiveHandoffMessage(event);
  });

  beginHandoffWait();

  /*
    The opener's origin cannot be read from here, so an undeclared ping has to
    go to '*'. It carries no data — it only says this tab is listening — and
    the sender is checked when the file itself arrives.
  */
  const target = window.opener || (window.parent !== window ? window.parent : null);
  if (!target) return;

  const pingOrigin = isHandoffOriginAllowed(declaredOrigin) ? declaredOrigin : '*';
  const announce = () => {
    try {
      target.postMessage({ kvot: 'rb-ready' }, pingOrigin);
    } catch (e) {
      ignoreFailure('initHandoffReceiver', e);
    }
  };

  announce();
  _handoffReadyPinger = setInterval(announce, HANDOFF_READY_PING_MS);
}

/**
 * Load the file named by a ?url= parameter, if there is one.
 * Handles blob: URLs from a same-origin producer as well as https: ones.
 *
 * @returns {Promise<void>}
 */
async function initUrlParamLoad() {
  let url;
  try {
    url = new URLSearchParams(window.location.search).get('url');
  } catch (_) {
    return;
  }
  if (!url) return;

  setFileLoadProgress(0, 'Loading…');
  try {
    const fileName = await ingestHdf5FromUrl(url, 'initUrlParamLoad', (read, total) => {
      setFileLoadProgress(total ? read / total : null,
                          total
                            ? `Loading ${kvotFormatBytes(read)} of ${kvotFormatBytes(total)}…`
                            : `Loading ${kvotFormatBytes(read)}…`);
    });

    try { await ensureTreeWorkerReady(5000); } catch (_) { ignoreFailure('initUrlParamLoad', _); }
    setFileLoadProgress(1, 'Refreshing tree…');
    await updateTabs(true);
    hideFileLoadTicker();
    kvotTrace('[handoff] Opened', fileName, 'from ?url=');
  } catch (err) {
    hideFileLoadTicker();
    reportFailure('handoff:urlParam', err, {
      userMessage: `Could not open the file at the address in the link: ${err.message}`
    });
  }
}

initHandoffReceiver();
initUrlParamLoad();
