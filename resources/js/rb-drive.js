/* ==========================================================================
   GOOGLE DRIVE

   Files picked from the reader's Google Drive, opened as a file from disk is:
   the bytes come from Google's Drive API straight into this page, are read
   here, and go nowhere else.

     1. The Google Drive button is shown only when rb-drive-config.js names a
        Google Cloud project.
     2. The first click in a tab opens a dialog that says what will happen,
        and starts loading Google's two scripts: its sign-in (Google Identity
        Services) and its file picker. Nothing of Google's is loaded before
        that click. Neither script has a version or fixed content, so unlike
        every other script this page runs they cannot be pinned by hash;
        loading them only for a reader who asks for Drive keeps them off the
        page for everyone else.
     3. Its "Choose files" asks Google for access to drive.file: the files the
        reader picks with this page, and nothing else of their Drive (Google
        classes it as non-sensitive). Google's sign-in opens in a window of
        its own, which a browser lets a page open only from a click; the
        scripts are loaded by the time of that click, so the window opens
        within it and no pop-up blocker stands in the way.
     4. Google's picker: My Drive, what is shared with the reader, shared
        drives, several files at once.
     5. Each file picked is fetched from the Drive API and opened by
        ingestFileBuffer, as a file from disk is. A large HDF5 file -- at the
        size from which one from disk is read as it is looked at -- is read
        the same way, a piece at a time, by the worker that reads those
        (rb-lazy-worker.js), each piece a request for that range of its bytes.

   A later click goes straight to the picker while the access lasts (Google
   gives it for an hour), and after that asks Google again from the click
   itself: once the reader has agreed, Google's window closes by itself.

   THE TOKEN is kept in this script's memory and nowhere else, never in
   storage, and is gone when the tab closes. It is attached ONLY in
   driveFileRequest, to a URL that function builds itself for
   www.googleapis.com from a file ID the picker gave. Nothing else on the page
   sends it anywhere. The worker reading a large file is handed that URL with
   those headers, and sends them to that URL alone; when Google gives a new
   token, the files it reads are handed the new headers.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/** Access to the files the reader picks with this page, and to no others. */
const DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file';
const DRIVE_SIGN_IN_SCRIPT = 'https://accounts.google.com/gsi/client';
const DRIVE_PICKER_SCRIPT = 'https://apis.google.com/js/api.js';
const DRIVE_FILES_API = 'https://www.googleapis.com/drive/v3/files/';

let driveToken = null;          // { value, expires }, expires in ms since the epoch
let driveTokenClient = null;    // Google's token client, once its script is loaded
let driveAskedThisTab = false;  // whether Google has answered once in this tab
let driveLoading = null;        // the promise of Google's scripts, once asked for
let drivePicker = null;         // the picker on show, to be disposed of
let driveQueue = Promise.resolve();  // one pick's files opened after another's
/** Files read a piece at a time, by their number in the worker: given new headers with a new token. */
const driveLazyFiles = new Map();

/**
 * The Google Cloud project from rb-drive-config.js, or null while it is not
 * filled in (or the file did not load).
 *
 * @returns {{clientId: string, apiKey: string, appId: string}|null}
 */
function driveConfig() {
  if (typeof RB_GOOGLE_DRIVE === 'undefined' || !RB_GOOGLE_DRIVE) return null;
  const { clientId, apiKey, appId } = RB_GOOGLE_DRIVE;
  const filled = [clientId, apiKey, appId].every(v => typeof v === 'string' && v.trim() !== '');
  return filled ? { clientId: clientId.trim(), apiKey: apiKey.trim(), appId: appId.trim() } : null;
}

/**
 * Show the Google Drive button, and the welcome text that names it, when a
 * project is configured and the page has the button (the VS Code build takes
 * it out). `rb-drive-ready` on the root element shows what is marked
 * `.rb-drive-only`, which survives the welcome panel being drawn again.
 */
function setUpGoogleDrive() {
  const buttons = document.querySelectorAll('[data-on-click="openGoogleDrive"]');
  if (!driveConfig() || buttons.length === 0) return;
  for (const button of buttons) button.hidden = false;
  document.documentElement.classList.add('rb-drive-ready');

  const dialog = document.getElementById('driveDialog');
  if (dialog) {
    dialog.addEventListener('click', (e) => {
      if (e.target === dialog) closeDriveDialog();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && dialog.style.display !== 'none') {
        e.preventDefault();
        closeDriveDialog();
      }
    });
  }
}

/* ── the button and the dialog ───────────────────────────────────────── */

/**
 * The Google Drive button. With Google's scripts loaded it goes straight on:
 * to the picker while the access lasts, else to Google for it, from this
 * click. The first time in a tab it opens the dialog instead.
 */
function openGoogleDrive() {
  if (!driveConfig()) return;
  if (driveTokenClient) {
    if (driveTokenValid()) showDrivePicker();
    else requestDriveToken();
    return;
  }
  openDriveDialog();
}

/**
 * Open the dialog and start loading Google's scripts behind it.
 *
 * @param {string} [message] - An error to show in it
 */
function openDriveDialog(message = '') {
  const dialog = document.getElementById('driveDialog');
  if (!dialog) return;
  showDriveDialogError(message);
  dialog.style.display = '';
  if (driveTokenClient) {
    setDriveChooseState('ready');
    return;
  }
  setDriveChooseState('loading');
  loadGoogleDrive().then(
    () => setDriveChooseState('ready'),
    (err) => {
      showDriveDialogError(err.message);
      setDriveChooseState('failed');
    });
}

/** Close the dialog. */
function closeDriveDialog() {
  const dialog = document.getElementById('driveDialog');
  if (dialog) dialog.style.display = 'none';
}

/**
 * The dialog's Choose files button: ask Google for access, from this click.
 * After a failure to load Google's scripts it is Try again, and loads them.
 */
function chooseDriveFiles() {
  if (!driveTokenClient) {
    openDriveDialog();
    return;
  }
  showDriveDialogError('');
  requestDriveToken();
}

/**
 * @param {'loading'|'ready'|'failed'} state
 */
function setDriveChooseState(state) {
  const button = document.getElementById('driveChooseBtn');
  if (!button) return;
  button.disabled = state === 'loading';
  button.textContent = state === 'loading' ? 'Connecting…' : state === 'failed' ? 'Try again' : 'Choose files…';
  if (state === 'ready' && document.getElementById('driveDialog').style.display !== 'none') button.focus();
}

/** @param {string} message - Empty to hide the dialog's error */
function showDriveDialogError(message) {
  const el = document.getElementById('driveError');
  if (!el) return;
  el.textContent = message || '';
  el.style.display = message ? '' : 'none';
}

/* ── Google's scripts ────────────────────────────────────────────────── */

/**
 * Load Google's sign-in and picker scripts, once, and set up the sign-in;
 * another try after a failure loads again only what failed.
 *
 * @returns {Promise<void>}
 */
function loadGoogleDrive() {
  if (!driveLoading) {
    driveLoading = (async () => {
      await Promise.all([loadDriveScript(DRIVE_SIGN_IN_SCRIPT, 'Google’s sign-in'),
                         loadDriveScript(DRIVE_PICKER_SCRIPT, 'Google’s file picker')]);
      const google = window.google;
      if (!window.gapi || typeof window.gapi.load !== 'function'
          || !google || !google.accounts || !google.accounts.oauth2) {
        throw new Error('Google’s scripts loaded, but not as this page expects them.');
      }
      await new Promise((resolve, reject) => {
        window.gapi.load('picker', {
          callback: resolve,
          onerror: () => reject(new Error('Google’s file picker could not be loaded.')),
          timeout: 20000,
          ontimeout: () => reject(new Error('Google’s file picker took too long to load.'))
        });
      });
      driveTokenClient = window.google.accounts.oauth2.initTokenClient({
        client_id: driveConfig().clientId,
        scope: DRIVE_SCOPE,
        callback: onDriveToken,
        error_callback: onDriveTokenError
      });
    })();
    driveLoading.catch(() => { driveLoading = null; });
  }
  return driveLoading;
}

/** Google's scripts by address: each is loaded once, and again only after it failed. */
const driveScripts = new Map();

/**
 * One of Google's scripts, as a script element: a script from another site
 * can only be run that way, and neither of these can be fetched and checked
 * first, since neither has a fixed content to check it against.
 *
 * @param {string} src
 * @param {string} what - Its name, for the message when it does not load
 * @returns {Promise<void>}
 */
function loadDriveScript(src, what) {
  if (!driveScripts.has(src)) {
    driveScripts.set(src, new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => {
        script.remove();
        driveScripts.delete(src);
        reject(new Error(`${what} could not be loaded from ${new URL(src).host}. `
          + 'A content blocker, or no connection to the internet, can stop it.'));
      };
      document.head.appendChild(script);
    }));
  }
  return driveScripts.get(src);
}

/* ── access ──────────────────────────────────────────────────────────── */

/** Whether the access Google gave lasts at least another minute. */
function driveTokenValid() {
  return !!driveToken && Date.now() < driveToken.expires;
}

/**
 * Ask Google for access. It must run within a click: Google's sign-in opens
 * a window of its own. The first time in a tab Google lets the reader choose
 * an account; after that it asks only for what has not been agreed to.
 */
function requestDriveToken() {
  driveTokenClient.requestAccessToken(driveAskedThisTab ? { prompt: '' } : {});
}

/**
 * Google's answer. Access refused, or the box for Drive left unticked on
 * Google's page, is said in the dialog; access given opens the picker.
 *
 * @param {{access_token?: string, expires_in?: number|string, scope?: string,
 *          error?: string, error_description?: string}} response
 */
function onDriveToken(response) {
  // Google has answered, so the reader has been to its page: an account is chosen.
  driveAskedThisTab = true;
  if (!response || response.error) {
    const error = response && response.error;
    const why = error === 'access_denied'
      ? 'Google Drive was not opened: access was not given.'
      : `Google did not give access (${error || 'no answer'}${response && response.error_description ? `: ${response.error_description}` : ''}).`;
    openDriveDialog(why);
    return;
  }
  if (!window.google.accounts.oauth2.hasGrantedAllScopes(response, DRIVE_SCOPE)) {
    openDriveDialog('Google Drive was not opened: the access to open the files you pick was '
      + 'not given. Choose files again, and tick it on Google’s page.');
    return;
  }
  // Google's tokens last an hour; one is let go a minute early, so that a
  // file is never asked for with a token about to run out.
  const seconds = Number(response.expires_in);
  const life = Number.isFinite(seconds) && seconds > 0 ? seconds : 3600;
  driveToken = { value: response.access_token, expires: Date.now() + Math.max(life - 60, life / 2) * 1000 };
  // The files open and read a piece at a time go on with the new access.
  for (const [fid, file] of driveLazyFiles) {
    const request = driveFileRequest(file);
    rbLazyCall('headers', { fid, headers: request.headers }).catch(() => driveLazyFiles.delete(fid));
  }
  closeDriveDialog();
  showDrivePicker();
}

/**
 * Google's sign-in window did not open, or was closed before it finished.
 *
 * @param {{type?: string}} err
 */
function onDriveTokenError(err) {
  const type = err && err.type;
  if (type === 'popup_failed_to_open') {
    openDriveDialog('The browser did not let Google’s sign-in window open. Choose files '
      + 'again, or allow pop-ups for this site.');
  } else if (type === 'popup_closed') {
    // Closed by the reader: nothing to say unless the dialog is up.
    if (document.getElementById('driveDialog').style.display !== 'none') {
      showDriveDialogError('Google’s sign-in window was closed before it finished.');
    }
  } else {
    openDriveDialog(`Google’s sign-in did not finish${type ? ` (${type})` : ''}.`);
  }
}

/* ── the picker ──────────────────────────────────────────────────────── */

/**
 * Google's picker, over the page: the reader's folders from the top of My
 * Drive, what is shared with them, and shared drives; in a list, since
 * drive.file shows no thumbnails; several files at once.
 */
function showDrivePicker() {
  const config = driveConfig();
  const P = window.google.picker;
  if (drivePicker) {
    try { drivePicker.dispose(); } catch (_) { ignoreFailure('showDrivePicker', _); }
    drivePicker = null;
  }
  const list = (view) => view.setMode(P.DocsViewMode.LIST);
  const myDrive = list(new P.DocsView(P.ViewId.DOCS)
    .setParent('root').setIncludeFolders(true).setSelectFolderEnabled(false));
  const shared = list(new P.DocsView(P.ViewId.DOCS).setOwnedByMe(false));
  const drives = list(new P.DocsView(P.ViewId.DOCS)
    .setEnableDrives(true).setIncludeFolders(true).setSelectFolderEnabled(false));
  drivePicker = new P.PickerBuilder()
    .addView(myDrive)
    .addView(shared)
    .addView(drives)
    .enableFeature(P.Feature.MULTISELECT_ENABLED)
    .setTitle('Open in the Data Browser')
    .setOAuthToken(driveToken.value)
    .setDeveloperKey(config.apiKey)
    .setAppId(config.appId)
    .setCallback(onDrivePicked)
    .build();
  drivePicker.setVisible(true);
}

/**
 * The picker's answer: the files picked are opened after any picked before
 * them; a cancel does nothing.
 *
 * @param {object} data - Google's response object
 */
function onDrivePicked(data) {
  const P = window.google.picker;
  const action = data && (data[P.Response.ACTION] || data.action);
  if (action !== P.Action.PICKED && action !== P.Action.CANCEL && action !== P.Action.ERROR) return;
  if (drivePicker) {
    try { drivePicker.dispose(); } catch (_) { ignoreFailure('onDrivePicked', _); }
    drivePicker = null;
  }
  if (action === P.Action.ERROR) {
    reportFailure('googleDrive:picker', new Error('the picker reported an error'),
                  { userMessage: 'Google’s file picker did not open.' });
    return;
  }
  if (action !== P.Action.PICKED) return;
  const docs = data[P.Response.DOCUMENTS] || data.docs || [];
  const files = docs.map(driveDocument).filter(Boolean);
  if (files.length === 0) return;
  driveQueue = driveQueue
    .then(() => openDriveFiles(files))
    .catch(err => reportFailure('googleDrive:queue', err, { userMessage: 'Opening files from Google Drive failed.' }));
}

/**
 * A picked file as this page uses it, or null when the picker gave no usable
 * ID. The ID and the resource key go into a URL and a header, so they are
 * held to the characters Drive uses for them.
 *
 * @param {object} doc - Google's document object
 * @returns {{id: string, name: string, mimeType: string, size: number,
 *            resourceKey: string}|null}
 */
function driveDocument(doc) {
  if (!doc || typeof doc !== 'object') return null;
  const D = window.google.picker.Document || {};
  const id = String(doc[D.ID || 'id'] || '');
  if (!/^[A-Za-z0-9_-]{1,200}$/.test(id)) {
    reportFailure('googleDrive:pick', new Error(`the picker gave the file ID ${JSON.stringify(id.slice(0, 40))}`),
                  { userMessage: 'A file picked in Google Drive could not be opened.' });
    return null;
  }
  const key = String(doc.resourceKey || '');
  const size = Number(doc.sizeBytes);
  return {
    id,
    name: driveFileName(doc[D.NAME || 'name'], id),
    mimeType: String(doc[D.MIME_TYPE || 'mimeType'] || ''),
    size: Number.isFinite(size) && size >= 0 ? size : NaN,
    resourceKey: /^[A-Za-z0-9_-]{1,200}$/.test(key) ? key : ''
  };
}

/**
 * A Drive file's name as a name for its tab. Drive lets a name hold a slash,
 * which a file on disk cannot, and anything else; the name keys the file
 * here, as on disk, so it is kept to one line and one level, and to a length
 * a tab can show, its extension kept.
 *
 * @param {*} name
 * @param {string} id - The file's ID, for a name that is empty
 * @returns {string}
 */
function driveFileName(name, id) {
  let clean = String(name == null ? '' : name)
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .replace(/[\\/]/g, '_')
    .trim();
  if (!clean || clean === '.' || clean === '..') clean = `drive-${id.slice(0, 12)}`;
  if (clean.length > 120) {
    const dot = clean.lastIndexOf('.');
    const ext = dot > 0 && clean.length - dot <= 10 ? clean.slice(dot) : '';
    clean = clean.slice(0, 120 - ext.length) + ext;
  }
  return clean;
}

/* ── the files ───────────────────────────────────────────────────────── */

/**
 * What to ask the Drive API for a file's bytes, with the access attached.
 * THE ONLY PLACE THE TOKEN IS ATTACHED, and only to a URL built here, for
 * www.googleapis.com, from a file ID the picker gave and driveDocument
 * checked. null when the access has run out. A part of the file is asked
 * for with these and a Range header, here for its first megabyte and by
 * rb-lazy-worker.js for each piece of a file read a piece at a time.
 *
 * @param {{id: string, resourceKey: string}} file
 * @returns {{url: string, headers: object}|null}
 */
function driveFileRequest(file) {
  if (!driveTokenValid()) return null;
  const headers = { Authorization: `Bearer ${driveToken.value}` };
  // A file shared by link may need its resource key as well as its ID.
  if (file.resourceKey) headers['X-Goog-Drive-Resource-Keys'] = `${file.id}/${file.resourceKey}`;
  return {
    url: `${DRIVE_FILES_API}${encodeURIComponent(file.id)}?alt=media&supportsAllDrives=true`,
    headers
  };
}

/**
 * A file's bytes from the Drive API.
 *
 * @param {object} file - From driveDocument
 * @param {function(number, number|null): void} [onProgress] - (bytesRead, bytesTotal|null)
 * @returns {Promise<ArrayBuffer>}
 */
async function fetchDriveFile(file, onProgress) {
  const request = driveFileRequest(file);
  if (!request) {
    throw new Error('Google’s access has run out (it lasts an hour). Click Google Drive and pick the file again.');
  }
  const response = await fetch(request.url, { headers: request.headers });
  if (!response.ok) throw new Error(await explainDriveFailure(response, file));
  return readResponseWithProgress(response, onProgress);
}

/* ── a large file, a piece at a time ─────────────────────────────────── */

/**
 * Whether a Drive file is read a piece at a time, as a file from disk is:
 * an HDF5 file (an assessment, a MAT-file, a JSON or XML file is written as
 * HDF5 in memory, so it is read whole) of the size from which one from disk
 * is, or as `localStorage['kvot-rb-lazy']` says (wantsLazyFile). Its size
 * must be known: the reader is told it.
 *
 * @param {{name: string, size: number}} file
 * @returns {boolean}
 */
function driveWantsLazy(file) {
  if (!(Number.isFinite(file.size) && file.size > 0)) return false;
  if (isEcolegoAssessment(file.name, null) || isMatFile(file.name, null)
      || isJsonFile(file.name, null) || isXmlFile(file.name, null)) return false;
  return wantsLazyFile({ size: file.size });
}

/**
 * Bytes [start, end) of a Drive file, asked for as a range. Drive answers a
 * range with that range (206); one that sent the whole file instead is
 * stopped, unless the range was the whole file.
 *
 * @param {object} file - From driveDocument
 * @param {number} start
 * @param {number} end
 * @returns {Promise<ArrayBuffer>}
 */
async function fetchDriveRange(file, start, end) {
  const request = driveFileRequest(file);
  if (!request) {
    throw new Error('Google’s access has run out (it lasts an hour). Click Google Drive and pick the file again.');
  }
  const response = await fetch(request.url, { headers: { ...request.headers, Range: `bytes=${start}-${end - 1}` } });
  if (!response.ok) throw new Error(await explainDriveFailure(response, file));
  if (response.status !== 206 && !(start === 0 && end >= file.size)) {
    try { await response.body.cancel(); } catch (_) { ignoreFailure('fetchDriveRange', _); }
    throw new Error(`Google Drive sent the whole of ${file.name} where a part of it was asked for, so it cannot be read a piece at a time.`);
  }
  return response.arrayBuffer();
}

/** How rb-lazy-worker.js says a request under a read failed. */
const DRIVE_READ_FAILURE = /could not be read over the network: (.*)$/;

/**
 * What a reader is told when a piece of a Drive file could not be fetched,
 * or null when the failure was not a request's (HDF5's own errors are said
 * as for any file). A 401 means the hour's access has run out: it is
 * forgotten, so that the next click on Google Drive asks Google again, and
 * the new access then reaches the files already open (onDriveToken).
 *
 * @param {{name: string}} file
 * @param {Error|string} err
 * @returns {string|null}
 */
function driveReadFailureText(file, err) {
  const m = DRIVE_READ_FAILURE.exec(String(err && err.message || err));
  if (!m) return null;
  const why = m[1];
  if (/^HTTP 401\b/.test(why)) {
    driveToken = null;
    return `Google’s access to ${file.name} has run out (it lasts an hour). Click Google Drive to renew it, then select again: the file stays open.`;
  }
  if (why === 'the connection failed') {
    return `${file.name} could not be read from Google Drive: the connection failed. Select again once it is back.`;
  }
  return `${file.name} could not be read from Google Drive (${why}).`;
}

/**
 * The worker, asked for one Drive file as rbLazyCall asks it, with what goes
 * wrong over the network said to the reader: the page reads a lazy file's
 * groups and values quietly, and a file from disk does not fail that way.
 *
 * @param {object} file - From driveDocument
 * @returns {function(string, Object): Promise}
 */
function driveLazyCall(file) {
  const tell = (err) => {
    const text = driveReadFailureText(file, err);
    if (text) reportFailure('googleDrive:read', err instanceof Error ? err : new Error(String(err)), { userMessage: text });
  };
  return async (cmd, args) => {
    if (cmd === 'close') driveLazyFiles.delete(args.fid);
    let answer;
    try {
      answer = await rbLazyCall(cmd, args);
    } catch (err) {
      if (cmd !== 'open') tell(err);   // a failed open is said by openDriveFiles
      throw err;
    }
    if (cmd === 'values' && answer && answer.errors) {
      const failed = Object.values(answer.errors).find(m => DRIVE_READ_FAILURE.test(m));
      if (failed) tell(failed);
    }
    return answer;
  };
}

/**
 * Open a large HDF5 file from Drive a piece at a time and register it as a
 * file from disk read that way is (registerLazyFile). Its first megabyte is
 * fetched here, for the HDF5 signature; then the worker reads what is looked
 * at, each piece a request for that range.
 *
 * @param {object} file - From driveDocument
 * @returns {Promise<string>} The name the file was registered under
 */
async function openDriveFileLazily(file) {
  const head = await fetchDriveRange(file, 0, Math.min(file.size, 1024 * 1024 + 8));
  const check = validateHdf5Buffer(head);
  if (!check.ok) throw new Error(`${file.name}: ${check.reason}`);
  const request = driveFileRequest(file);
  if (!request) {
    throw new Error('Google’s access has run out (it lasts an hour). Click Google Drive and pick the file again.');
  }
  const call = driveLazyCall(file);
  let opened;
  try {
    opened = await call('open', { remote: { url: request.url, headers: request.headers, size: file.size } });
  } catch (err) {
    throw new Error(driveReadFailureText(file, err) || err.message);
  }
  driveLazyFiles.set(opened.fid, file);
  return registerLazyFile(file.name, opened, call, 'googleDrive:lazy');
}

/**
 * The reason a Drive request failed, in words, from the status and the
 * reason Google gives in its error. A 401 means the access is no longer
 * good, so it is forgotten and the next click asks again.
 *
 * @param {Response} response
 * @param {{name: string}} file
 * @returns {Promise<string>}
 */
async function explainDriveFailure(response, file) {
  let reason = '';
  let message = '';
  try {
    const body = JSON.parse((await response.text()).slice(0, 20000));
    const error = body && body.error;
    if (error && typeof error === 'object') {
      if (Array.isArray(error.errors) && error.errors[0]) reason = String(error.errors[0].reason || '');
      message = String(error.message || '');
    }
  } catch (_) { ignoreFailure('explainDriveFailure', _); }

  const name = file.name;
  const status = response.status;
  if (status === 401) {
    driveToken = null;
    return 'Google no longer accepts the access given (it lasts an hour). Click Google Drive and pick the file again.';
  }
  if (reason === 'cannotDownloadFile') return `The owner of ${name} does not let it be downloaded, so it cannot be opened here.`;
  if (reason === 'cannotDownloadAbusiveFile') return `Google has marked ${name} as possibly harmful, and only its owner can download it.`;
  if (reason === 'fileNotDownloadable') return `${name} lives only in Google Drive, as a Google Docs, Sheets or Slides file does, and has no file of its own to open here.`;
  if (reason === 'appNotAuthorizedToFile' || reason === 'insufficientFilePermissions') {
    return `Google Drive did not give this page access to ${name}. Click Google Drive and pick it again.`;
  }
  if (reason === 'downloadQuotaExceeded') return `${name} has been downloaded too often lately, and Google lets it be downloaded again later.`;
  if (status === 429 || /rateLimitExceeded|dailyLimitExceeded/i.test(reason)) {
    return 'Google Drive is turning requests away just now. Try again in a minute.';
  }
  if (status === 404) return `Google Drive has no file ${name} that this page may open: it may have been deleted, or shared differently since it was picked.`;
  return `Google Drive answered HTTP ${status}${reason ? ` (${reason})` : ''}${message ? `: ${message}` : ''}`;
}

/**
 * Why a picked file cannot be fetched at all, before trying: a folder, a
 * shortcut, or a file that lives only in Google Drive (Docs, Sheets,
 * Slides, ...) has no bytes of its own; '' when it can.
 *
 * @param {{name: string, mimeType: string}} file
 * @returns {string}
 */
function driveFileRefusal(file) {
  const type = file.mimeType;
  if (!type.startsWith('application/vnd.google-apps.')) return '';
  if (type === 'application/vnd.google-apps.folder') return `${file.name} is a folder: open it in the picker and pick the files in it.`;
  if (type === 'application/vnd.google-apps.shortcut') return `${file.name} is a shortcut: pick the file it points to.`;
  return `${file.name} lives only in Google Drive, as a Google Docs, Sheets or Slides file does, and has no file of its own to open here.`;
}

/**
 * Fetch the files picked, one after another, and open each as a file from
 * disk is opened; a file that fails is reported and the rest still open.
 *
 * @param {Array<object>} files - From driveDocument
 * @returns {Promise<void>}
 */
async function openDriveFiles(files) {
  const total = files.length;
  showFileLoadTicker(0, total, 'Starting…');
  try {
    await waitForH5Wasm();
    for (let i = 0; i < total; i++) {
      const file = files[i];
      updateFileLoadTicker(i, total, file.name);
      try {
        const refusal = driveFileRefusal(file);
        if (refusal) throw new Error(refusal);
        const count = total > 1 ? `${i + 1}/${total} — ` : '';
        if (driveWantsLazy(file)) {
          // A piece at a time, whatever its size: only what is looked at is fetched.
          setFileLoadProgress(null, `${count}${file.name} — opening, to be read as it is looked at`);
          await openDriveFileLazily(file);
          kvotTrace('[googleDrive] Opened a piece at a time', file.name);
          continue;
        }
        // Read whole, so held to the limit a file read whole from disk has.
        const size = kvotFileTooLarge(file, KVOT_FILE_SIZE_LIMITS.dataset);
        if (size.tooLarge) throw new Error(size.reason);
        const buffer = await fetchDriveFile(file, (read, length) => {
          setFileLoadProgress(length ? read / length : null,
            `${count}${file.name} — ${kvotFormatBytes(read)}${length ? ` of ${kvotFormatBytes(length)}` : ''}`);
        });
        await ingestFileBuffer(file.name, buffer, 'googleDrive:load');
        kvotTrace('[googleDrive] Opened', file.name);
      } catch (err) {
        reportFailure('googleDrive:load', err, { userMessage: `Could not open ${file.name} from Google Drive.` });
      }
    }
    try { await ensureTreeWorkerReady(5000); } catch (_) { ignoreFailure('openDriveFiles', _); }
    updateFileLoadTicker(total, total, 'Refreshing tree…');
    await updateTabs(true);
    hideFileLoadTicker();
  } catch (err) {
    hideFileLoadTicker();
    reportFailure('googleDrive:open', err, { userMessage: 'Opening files from Google Drive failed.' });
  }
}

setUpGoogleDrive();
