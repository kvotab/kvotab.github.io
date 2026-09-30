/* ==========================================================================
   UPDATES

   The extension comes from the site (the VS Code button on kvotab.se/rb.html),
   not from VS Code's Marketplace, so VS Code never looks for a newer version
   of it. This does: it reads the release note release.mjs publishes with each
   version (rb-vscode/dist/latest.json), and when the version there is newer
   than the one running, it downloads the package, checks it, and has VS Code
   install it, as Install from VSIX would. The new version starts when the
   window is reloaded, which it then offers.

   Only a package that was released is installed. release.mjs signs the
   extension's id, the version and the package's SHA-256 with a key kept off
   the repository, and the signature must verify with the public key this
   extension carries (release-public-key.pem). Whoever could change the site,
   or the connection to it, could hold an update back, but could not have
   anything of their own installed, nor an older release as a newer one: the
   version is signed with the package.

   When: a while after VS Code starts and then every hour, if no window of
   this VS Code has looked for LOOK_EVERY_MS. hdf5Browser.updates says what a
   newer version leads to: installed (install, the default), offered
   (notify), or nothing until asked (off). VS Code's own Extensions: Auto
   Update and Auto Check Updates settings, when off, hold it back the same way
   they hold back VS Code's updates of extensions. "HDF5 Browser: Check for
   Updates" looks at once, whatever the settings say.

   The note and the package are fetched as any of the site's files are:
   nothing is sent about the machine, the user or their files.

   Tests: test/test-update.mjs works this module with a stand-in for VS Code;
   test/test-update.py updates an installed copy in a real one, which it
   points at a server and a key of its own (KVOT_HDF5_UPDATE_URL and
   KVOT_HDF5_UPDATE_KEY).
   ========================================================================== */

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

/** Where release.mjs publishes: the note, and the package it describes. */
const RELEASES = 'https://kvotab.se/rb-vscode/dist/';
const NOTE_FILE = 'latest.json';
const PACKAGE_FILE = 'hdf5-browser.vsix';
/** The page to get a version from by hand. */
const SITE_PAGE = 'https://kvotab.se/rb.html';
/** The first look, this long after the extension starts: VS Code's own start comes first. */
const FIRST_LOOK_MS = 20 * 1000;
/** How often a window asks whether it is time to look again; */
const POLL_MS = 60 * 60 * 1000;
/** and how long a look holds, for every window. */
const LOOK_EVERY_MS = 12 * 60 * 60 * 1000;
const NOTE_TIMEOUT_MS = 30 * 1000;
const PACKAGE_TIMEOUT_MS = 10 * 60 * 1000;
/** No package of this extension comes near this (0.1.4 is 4.5 MB). */
const PACKAGE_MAX_BYTES = 64 * 1024 * 1024;
/** A window installing an update holds the lock; one older than this was left by a window that went away. */
const LOCK_STALE_MS = 10 * 60 * 1000;
const LAST_LOOK_KEY = 'updates.lastLook';
const MODES = new Set(['install', 'notify', 'off']);
const RELOAD = 'Reload Window';
const INSTALL = 'Install';
const NOT_NOW = 'Not Now';
const SHOW_LOG = 'Show Log';
const FROM_SITE = 'Download from kvotab.se';

/* ── versions, notes and signatures ──────────────────────────────────── */

/** [major, minor, patch] of an x.y.z version, or null. */
function parseVersion(v) {
  const m = /^(\d{1,9})\.(\d{1,9})\.(\d{1,9})$/.exec(String(v));
  return m ? m.slice(1).map(Number) : null;
}

/** Whether version `a` is newer than `b`; false when either is not x.y.z. */
function isNewer(a, b) {
  const x = parseVersion(a);
  const y = parseVersion(b);
  if (!x || !y) return false;
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

/** The oldest VS Code an engines range such as "^1.100.0" admits, as x.y.z; null when it does not say plainly. */
function oldestVscode(range) {
  const m = /^\s*(?:\^|>=)?\s*(\d+)\.(\d+)\.(\d+)/.exec(String(range || ''));
  return m ? `${m[1]}.${m[2]}.${m[3]}` : null;
}

/** Whether the VS Code running (1.135.0, or 1.136.0-insider) is `oldest` or later; true when either cannot be read, for VS Code to decide. */
function vscodeIsAtLeast(running, oldest) {
  const plain = String(running).split('-')[0];
  if (!parseVersion(plain) || !parseVersion(oldest)) return true;
  return !isNewer(oldest, plain);
}

/** What a release's signature is over: the extension, its version and the package's SHA-256 (release.mjs signs it). */
function signedText(id, version, sha256) {
  return `kvotab release\n${id}\n${version}\n${sha256}\n`;
}

/** The signature release.mjs puts in the note, base64. */
function signRelease(privateKey, id, version, sha256) {
  return crypto.sign(null, Buffer.from(signedText(id, version, sha256), 'utf8'), privateKey).toString('base64');
}

/** Whether `signature` is the release key's over this extension, version and hash. */
function verifyRelease(publicKey, id, version, sha256, signature) {
  try {
    return crypto.verify(null, Buffer.from(signedText(id, version, sha256), 'utf8'), publicKey, Buffer.from(String(signature), 'base64'));
  } catch (_) {
    return false;
  }
}

/** A note as the site serves it, read: the version first, as that is all an up-to-date copy needs of it. */
function readNote(text) {
  let note;
  try {
    note = JSON.parse(text);
  } catch (e) {
    throw new Error(`the release note is not JSON (${e.message})`);
  }
  if (!note || typeof note !== 'object' || !parseVersion(note.version)) throw new Error('the release note names no version');
  return note;
}

/** What a note of a newer version must also say before anything is downloaded. */
function checkNewNote(note) {
  if (!/^[0-9a-f]{64}$/.test(String(note.sha256))) throw new Error('the release note gives no SHA-256 of the package');
  if (!Number.isSafeInteger(note.bytes) || note.bytes <= 0 || note.bytes > PACKAGE_MAX_BYTES) {
    throw new Error('the release note gives no size of the package, or one no package of it has');
  }
  // Ed25519: 64 bytes, 88 characters of base64.
  if (!/^[A-Za-z0-9+/]{86}==$/.test(String(note.signature || ''))) throw new Error('the release note is not signed');
}

/* ── the network ─────────────────────────────────────────────────────── */

/** An error of this module's, said as it is (a network's is said with what was being fetched). */
function plainly(message) {
  const e = new Error(message);
  e.plain = true;
  return e;
}

/** An error that means the release is not believed: never installed, and not to be fetched by hand either. */
function refusal(message) {
  const e = plainly(message);
  e.refusal = true;
  return e;
}

/** GET `url` and read its body with `read`, both within `ms`. */
async function fetchWithin(fetchFn, url, ms, what, read) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    const response = await fetchFn(url, { signal: controller.signal, redirect: 'follow' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await read(response);
  } catch (e) {
    if (e && e.plain) throw e;
    if (controller.signal.aborted) throw new Error(`${what}: no answer within ${Math.round(ms / 1000)} s`);
    const cause = e && e.cause && e.cause.message;
    throw new Error(`${what}: ${cause || (e && e.message) || e}`);
  } finally {
    clearTimeout(timer);
  }
}

/** The body, if it is no longer than `max` bytes; `tooLarge` makes the error when it is. */
async function readAtMost(response, max, tooLarge) {
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > max) {
      reader.cancel().catch(() => {});
      throw tooLarge();
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks, total);
}

/* ── the updater ─────────────────────────────────────────────────────── */

class Updater {
  /**
   * `vscode` is VS Code's API (a stand-in in test/test-update.mjs); `event`
   * reports what happened to a test, as the provider's does. `fetch`,
   * `releases` and `publicKey` default to the network, the site and the key
   * this extension carries.
   */
  constructor({ vscode, context, log, event, fetch: fetchFn, releases, publicKey }) {
    this.vscode = vscode;
    this.context = context;
    this.log = log;
    this.event = event || (() => {});
    this.fetch = fetchFn || globalThis.fetch;
    this.releases = releases || process.env.KVOT_HDF5_UPDATE_URL || RELEASES;
    const pkg = context.extension.packageJSON;
    this.id = `${pkg.publisher}.${pkg.name}`.toLowerCase();
    this.version = pkg.version;
    this.publicKey = publicKey || null;
    this.keyError = null;
    if (!this.publicKey) {
      try {
        const pem = process.env.KVOT_HDF5_UPDATE_KEY || fs.readFileSync(path.join(__dirname, 'release-public-key.pem'), 'utf8');
        this.publicKey = crypto.createPublicKey(pem);
      } catch (e) {
        this.keyError = `this copy has no key to check a release with (${e.message})`;
      }
    }
    this.busy = null;         // the look under way
    this.installing = null;   // the install under way
    this.told = new Set();    // what this window has said already of what it found by itself
  }

  /** What a newer version found by looking leads to: hdf5Browser.updates, held back by VS Code's own settings when they are off. */
  mode() {
    const own = this.vscode.workspace.getConfiguration('hdf5Browser').get('updates', 'install');
    const mode = MODES.has(own) ? own : 'install';
    const extensions = this.vscode.workspace.getConfiguration('extensions');
    if (extensions.get('autoCheckUpdates') === false) return 'off';
    // Read as VS Code reads its own: off, false and onlySelectedExtensions
    // (which never selects an extension installed from a file) are off.
    const auto = extensions.get('autoUpdate');
    if (mode === 'install' && (auto === false || auto === 'off' || auto === 'onlySelectedExtensions')) return 'notify';
    return mode;
  }

  /** Look by itself from now on: once soon, then whenever the last look has grown old. */
  start() {
    const first = setTimeout(() => this.lookIfDue(), FIRST_LOOK_MS);
    const every = setInterval(() => this.lookIfDue(), POLL_MS);
    return { dispose: () => { clearTimeout(first); clearInterval(every); } };
  }

  async lookIfDue() {
    if (this.mode() === 'off') return;
    const last = this.context.globalState.get(LAST_LOOK_KEY, 0);
    const now = Date.now();
    if (now >= last && now - last < LOOK_EVERY_MS) return;
    // Noted before looking, so that the other windows do not all look too.
    await this.context.globalState.update(LAST_LOOK_KEY, now);
    await this.check(false);
  }

  /** Look for a newer version. `asked`: by the command, and whoever gave it is told what was found, whatever it is. */
  check(asked) {
    if (!this.busy) this.busy = this.look(!!asked).finally(() => { this.busy = null; });
    return this.busy;
  }

  async look(asked) {
    const { vscode } = this;
    let note;
    try {
      if (this.keyError) throw new Error(this.keyError);
      note = await this.readNote();
    } catch (e) {
      this.log.warn(`Looking for an update: ${e.message}`);
      this.event({ type: 'update', state: 'failed', message: e.message });
      if (asked) this.fail(`Could not look for an update of the HDF5 Browser: ${e.message}`);
      return;
    }
    if (!isNewer(note.version, this.version)) {
      this.log.info(`Looked for an update: ${this.version} is up to date (the site has ${note.version})`);
      this.event({ type: 'update', state: 'latest', version: note.version });
      if (asked) vscode.window.showInformationMessage(`The HDF5 Browser is up to date: ${this.version} is the latest version.`);
      return;
    }
    const version = note.version;
    const oldest = oldestVscode(note.vscode);
    if (oldest && !vscodeIsAtLeast(vscode.version, oldest)) {
      const text = `HDF5 Browser ${version} needs VS Code ${oldest} or later, and this is ${vscode.version}: update VS Code to have it.`;
      this.log.warn(text);
      this.event({ type: 'update', state: 'needsVscode', version, oldest });
      if (asked || this.tellOnce(`needs ${version}`)) vscode.window.showWarningMessage(text);
      return;
    }
    if (this.installedAlready(version)) {
      this.pending(version, asked);
      return;
    }
    if (this.context.extensionMode !== vscode.ExtensionMode.Production) {
      const text = `HDF5 Browser ${version} is out. This copy runs from its folder, not installed, so it is not updated.`;
      this.log.info(text);
      this.event({ type: 'update', state: 'development', version });
      if (asked) vscode.window.showInformationMessage(text);
      return;
    }
    try {
      checkNewNote(note);
    } catch (e) {
      this.refused(version, e.message, asked);
      return;
    }
    if (!verifyRelease(this.publicKey, this.id, version, note.sha256, note.signature)) {
      this.refused(version, 'its release note is not signed with the release key', asked);
      return;
    }
    const mode = asked ? (this.mode() === 'install' ? 'install' : 'notify') : this.mode();
    if (mode === 'off') return;
    if (mode === 'install') {
      await this.install(note, asked);
      return;
    }
    if (!asked && !this.tellOnce(`offer ${version}`)) return;
    this.log.info(`${version} is out; offered`);
    this.event({ type: 'update', state: 'offered', version });
    // Not awaited: an offer may wait in the notification centre for days, and
    // a look meanwhile (the command) must not wait for it.
    vscode.window.showInformationMessage(`HDF5 Browser ${version} is out; you have ${this.version}.`, INSTALL, NOT_NOW).then((choice) => {
      if (choice === INSTALL) return this.install(note, true);
      this.log.info(`${version} was not installed (${choice || 'the offer was closed'})`);
      return undefined;
    });
  }

  /** Whether this window has not said `what` yet: of what it found by itself, it says a thing once. */
  tellOnce(what) {
    if (this.told.has(what)) return false;
    this.told.add(what);
    return true;
  }

  readNote() {
    // The query keeps a cache on the way (the site's CDN holds a file for some
    // minutes) from answering with the note of the release before.
    const url = new URL(`${NOTE_FILE}?t=${Date.now()}`, this.releases).toString();
    return fetchWithin(this.fetch, url, NOTE_TIMEOUT_MS, 'the release note', async (response) => {
      const bytes = await readAtMost(response, 64 * 1024, () => plainly('the release note is larger than 64 KB'));
      try {
        return readNote(bytes.toString('utf8'));
      } catch (e) {
        throw plainly(e.message);
      }
    });
  }

  /** The package of `note`, downloaded and checked against it. */
  async download(note) {
    const url = new URL(`${PACKAGE_FILE}?v=${encodeURIComponent(note.version)}`, this.releases).toString();
    const bytes = await fetchWithin(this.fetch, url, PACKAGE_TIMEOUT_MS, 'the package',
      response => readAtMost(response, note.bytes, () => refusal('the package is larger than its release note says')));
    if (bytes.length !== note.bytes) throw new Error(`the package came to ${bytes.length} bytes, and its release note says ${note.bytes}`);
    const sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
    if (sha256 !== note.sha256) throw refusal('the package is not the one its release note names: its SHA-256 differs');
    return bytes;
  }

  /**
   * Whether `version` is installed already, by another window or before a
   * reload: VS Code puts each version in a folder of its own beside this
   * one's, and lists one it is to remove in .obsolete.
   */
  installedAlready(version) {
    const folders = path.dirname(this.context.extensionPath);
    const name = `${this.id}-${version}`;
    try {
      const pkg = JSON.parse(fs.readFileSync(path.join(folders, name, 'package.json'), 'utf8'));
      if (pkg.version !== version) return false;
    } catch (_) {
      return false;
    }
    try {
      const obsolete = JSON.parse(fs.readFileSync(path.join(folders, '.obsolete'), 'utf8'));
      return !(obsolete && obsolete[name]);
    } catch (_) {
      return true;
    }
  }

  /** `version` is installed and waits for a reload. */
  pending(version, asked) {
    this.log.info(`${version} is installed; it starts when the window is reloaded`);
    this.event({ type: 'update', state: 'pending', version });
    if (asked || this.tellOnce(`reload ${version}`)) this.offerReload(version);
  }

  /** One window installs at a time: every window runs this, and they look at the same moment when VS Code starts. */
  async lock() {
    const dir = this.context.globalStorageUri.fsPath;
    await fs.promises.mkdir(dir, { recursive: true });
    const file = path.join(dir, 'update.lock');
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        await fs.promises.writeFile(file, String(process.pid), { flag: 'wx' });
        return { release: () => fs.promises.unlink(file).catch(() => {}) };
      } catch (e) {
        if (e.code !== 'EEXIST') throw e;
        const stat = await fs.promises.stat(file).catch(() => null);
        if (stat && Date.now() - stat.mtimeMs < LOCK_STALE_MS) return null;
        await fs.promises.unlink(file).catch(() => {});
      }
    }
    return null;
  }

  /** Download, check and install `note`'s version; `visibly` shows the progress as a notification rather than in the status bar. */
  install(note, visibly) {
    if (!this.installing) this.installing = this.doInstall(note, visibly).finally(() => { this.installing = null; });
    return this.installing;
  }

  async doInstall(note, visibly) {
    const { vscode } = this;
    const version = note.version;
    if (this.installedAlready(version)) {
      this.pending(version, true);
      return;
    }
    let lock;
    try {
      lock = await this.lock();
    } catch (e) {
      this.failedInstall(version, e.message, visibly);
      return;
    }
    if (!lock) {
      this.log.info(`Another window is installing an update; ${version} is left to it`);
      this.event({ type: 'update', state: 'locked', version });
      if (visibly) vscode.window.showInformationMessage(`Another VS Code window is installing HDF5 Browser ${version}.`);
      return;
    }
    const file = path.join(this.context.globalStorageUri.fsPath, `hdf5-browser-${version}.vsix`);
    try {
      await vscode.window.withProgress({
        location: visibly ? vscode.ProgressLocation.Notification : vscode.ProgressLocation.Window,
        title: `HDF5 Browser ${version}`
      }, async (progress) => {
        progress.report({ message: 'downloading…' });
        this.log.info(`Downloading ${version}`);
        const bytes = await this.download(note);
        await fs.promises.writeFile(file, bytes);
        progress.report({ message: 'installing…' });
        await vscode.commands.executeCommand('workbench.extensions.installExtension', vscode.Uri.file(file));
      });
    } catch (e) {
      if (e && e.refusal) this.refused(version, e.message, visibly);
      else this.failedInstall(version, e && e.message ? e.message : String(e), visibly);
      return;
    } finally {
      await fs.promises.unlink(file).catch(() => {});
      await lock.release();
    }
    this.log.info(`Installed ${version}; it starts when the window is reloaded`);
    this.event({ type: 'update', state: 'installed', version });
    this.tellOnce(`reload ${version}`);
    this.offerReload(version);
  }

  offerReload(version) {
    const { vscode } = this;
    vscode.window.showInformationMessage(`HDF5 Browser ${version} is installed. Reload the window to start it.`, RELOAD).then((choice) => {
      if (choice === RELOAD) return vscode.commands.executeCommand('workbench.action.reloadWindow');
      return undefined;
    });
  }

  /**
   * A release that is not what its note says, or a note not signed: never
   * installed, and said once. Not sent to the site for it either: a package
   * that does not verify is the one thing not to install by hand.
   */
  refused(version, message, asked) {
    this.log.error(`Did not install ${version}: ${message}`);
    this.event({ type: 'update', state: 'refused', version, message });
    if (!asked && !this.tellOnce(`refused ${version}`)) return;
    this.vscode.window.showWarningMessage(`HDF5 Browser ${version} was not installed: ${message}.`, SHOW_LOG)
      .then(choice => this.follow(choice));
  }

  failedInstall(version, message, visibly) {
    this.log.error(`Installing ${version} failed: ${message}`);
    this.event({ type: 'update', state: 'failed', version, message });
    if (!visibly && !this.tellOnce(`failed ${version}`)) return;
    this.fail(`Could not install HDF5 Browser ${version}: ${message}`);
  }

  fail(text) {
    this.vscode.window.showErrorMessage(text, FROM_SITE, SHOW_LOG).then(choice => this.follow(choice));
  }

  follow(choice) {
    const { vscode } = this;
    if (choice === FROM_SITE) vscode.env.openExternal(vscode.Uri.parse(SITE_PAGE));
    else if (choice === SHOW_LOG) this.log.show();
  }
}

module.exports = {
  Updater,
  parseVersion,
  isNewer,
  oldestVscode,
  vscodeIsAtLeast,
  signedText,
  signRelease,
  verifyRelease,
  readNote,
  checkNewNote,
  RELEASES,
  PACKAGE_MAX_BYTES,
  LOOK_EVERY_MS,
  LAST_LOOK_KEY
};
