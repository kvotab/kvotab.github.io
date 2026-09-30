// The updater (src/update.js) against a site of its own, with a stand-in for
// VS Code's API: what it installs, what it refuses, and what it says.
//
//     node rb-vscode/test/test-update.mjs
//
// The site is a local server whose release note and package each case sets;
// the release key is one made here. Nothing is installed: the stand-in's
// installExtension keeps the bytes it was handed, for the test to compare
// with the package. test-update.py updates a real VS Code.
// Exit status is 0 when every check passes.

import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXTENSION = path.dirname(HERE);
const U = createRequire(import.meta.url)('../src/update.js');

let checks = 0;
const failures = [];
function check(label, got, want = true) {
  checks++;
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)} (expected ${JSON.stringify(want)})`}`);
  if (!ok) failures.push(label);
}

const ID = 'kvotab.hdf5-browser';
const release = crypto.generateKeyPairSync('ed25519');
const stranger = crypto.generateKeyPairSync('ed25519');
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'rb-update-'));

/* ── the site ─────────────────────────────────────────────────────────── */

const site = { note: null, noteStatus: 200, pkg: Buffer.alloc(0), requests: [] };
const server = http.createServer((req, res) => {
  site.requests.push(req.url);
  const url = new URL(req.url, 'http://site');
  if (url.pathname === '/dist/latest.json') {
    if (site.noteStatus !== 200 || site.note === null) {
      res.writeHead(site.note === null ? 404 : site.noteStatus);
      res.end('no');
      return;
    }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(typeof site.note === 'string' ? site.note : JSON.stringify(site.note));
    return;
  }
  if (url.pathname === '/dist/hdf5-browser.vsix') {
    res.writeHead(200, { 'Content-Type': 'application/octet-stream' });
    res.end(site.pkg);
    return;
  }
  res.writeHead(404);
  res.end();
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const BASE = `http://127.0.0.1:${server.address().port}/dist/`;
const packageRequests = () => site.requests.filter(r => r.startsWith('/dist/hdf5-browser.vsix')).length;
const noteRequests = () => site.requests.filter(r => r.startsWith('/dist/latest.json')).length;

/** A package (any bytes will do) and its release note, signed as release.mjs signs one. */
function publish(version, { bytes = crypto.randomBytes(3000), key = release.privateKey, signedVersion = version, vscode = '^1.100.0', drop = [] } = {}) {
  const note = {
    name: 'HDF5 Browser', version, file: 'hdf5-browser.vsix', bytes: bytes.length, sha256: sha(bytes),
    released: '2026-09-30T12:00:00.000Z', build: 'test', vscode, signature: U.signRelease(key, ID, signedVersion, sha(bytes))
  };
  for (const k of drop) delete note[k];
  site.note = note;
  site.noteStatus = 200;
  site.pkg = bytes;
  return bytes;
}

/* ── VS Code ──────────────────────────────────────────────────────────── */

/**
 * VS Code as the updater sees it: settings, the messages it shows (answered
 * by `answer(text, buttons)`, by default closed), the commands it runs, and an
 * installed copy of `version` in an extensions folder of its own.
 */
function vscodeWith({ settings = {}, answer = () => undefined, version = '0.1.5', mode = 1, vscodeVersion = '1.135.0', installFails = null } = {}) {
  const root = fs.mkdtempSync(path.join(temp, 'case-'));
  const extensions = path.join(root, 'extensions');
  const own = path.join(extensions, `${ID}-${version}`);
  fs.mkdirSync(own, { recursive: true });
  fs.writeFileSync(path.join(own, 'package.json'), JSON.stringify({ publisher: 'kvotab', name: 'hdf5-browser', version }));
  const t = { said: [], ran: [], opened: [], progress: [], installed: [], logs: [], events: [], root, extensions };
  const state = new Map();
  t.state = state;
  const say = (kind, text, buttons) => {
    t.said.push({ kind, text, buttons });
    return Promise.resolve(answer(text, buttons));
  };
  t.vscode = {
    version: vscodeVersion,
    ExtensionMode: { Production: 1, Development: 2, Test: 3 },
    ProgressLocation: { SourceControl: 1, Window: 10, Notification: 15 },
    Uri: { file: p => ({ scheme: 'file', fsPath: p }), parse: s => ({ scheme: 'https', toString: () => s }) },
    env: { openExternal: async (u) => { t.opened.push(String(u)); return true; } },
    workspace: {
      getConfiguration: section => ({ get: (key, fallback) => (`${section}.${key}` in settings ? settings[`${section}.${key}`] : fallback) })
    },
    window: {
      showInformationMessage: (text, ...buttons) => say('info', text, buttons),
      showWarningMessage: (text, ...buttons) => say('warning', text, buttons),
      showErrorMessage: (text, ...buttons) => say('error', text, buttons),
      withProgress: async (options, task) => {
        t.progress.push(options.location);
        return task({ report: () => {} });
      }
    },
    commands: {
      executeCommand: async (cmd, ...args) => {
        t.ran.push(cmd);
        if (cmd === 'workbench.extensions.installExtension') {
          t.installed.push({ bytes: fs.readFileSync(args[0].fsPath), file: args[0].fsPath });
          if (installFails) throw new Error(installFails);
        }
      }
    }
  };
  t.context = {
    extension: { packageJSON: { publisher: 'kvotab', name: 'hdf5-browser', version } },
    extensionPath: own,
    extensionMode: mode,
    globalStorageUri: { fsPath: path.join(root, 'storage') },
    globalState: { get: (k, fallback) => (state.has(k) ? state.get(k) : fallback), update: async (k, v) => { state.set(k, v); } }
  };
  const log = kind => (...parts) => t.logs.push(`${kind}: ${parts.join(' ')}`);
  t.log = { info: log('info'), warn: log('warn'), error: log('error'), show: () => t.ran.push('showLog') };
  t.updater = new U.Updater({
    vscode: t.vscode, context: t.context, log: t.log, event: e => t.events.push(e),
    releases: BASE, publicKey: release.publicKey
  });
  /** Everything the updater started has finished: the look, an install an answer began, and the messages' follow-ups. */
  t.settle = async () => {
    for (let i = 0; i < 5; i++) {
      await t.updater.busy;
      await new Promise(resolve => setImmediate(resolve));
      await t.updater.installing;
      await new Promise(resolve => setImmediate(resolve));
    }
  };
  t.texts = () => t.said.map(m => `${m.kind}: ${m.text}`);
  t.states = () => t.events.filter(e => e.type === 'update').map(e => e.state);
  return t;
}

/* ── versions and signatures ──────────────────────────────────────────── */

check('isNewer reads each part as a number', [U.isNewer('0.1.10', '0.1.9'), U.isNewer('0.2.0', '0.1.99'), U.isNewer('1.0.0', '1.0.0'),
  U.isNewer('0.1.4', '0.1.5'), U.isNewer('0.1.5.1', '0.1.5'), U.isNewer('x', '0.1.0')], [true, true, false, false, false, false]);
check('the oldest VS Code an engines range admits', [U.oldestVscode('^1.100.0'), U.oldestVscode('>=1.90.1'), U.oldestVscode('*'), U.oldestVscode(undefined)],
  ['1.100.0', '1.90.1', null, null]);
check('  and whether the one running is that or later', [U.vscodeIsAtLeast('1.135.0', '1.100.0'), U.vscodeIsAtLeast('1.99.3', '1.100.0'),
  U.vscodeIsAtLeast('1.136.0-insider', '1.136.0'), U.vscodeIsAtLeast('?', '1.100.0')], [true, false, true, true]);
const s0 = U.signRelease(release.privateKey, ID, '0.1.6', 'a'.repeat(64));
check('a signature verifies with the release key, over that id, version and hash only', [
  U.verifyRelease(release.publicKey, ID, '0.1.6', 'a'.repeat(64), s0),
  U.verifyRelease(stranger.publicKey, ID, '0.1.6', 'a'.repeat(64), s0),
  U.verifyRelease(release.publicKey, ID, '0.1.7', 'a'.repeat(64), s0),
  U.verifyRelease(release.publicKey, ID, '0.1.6', 'b'.repeat(64), s0),
  U.verifyRelease(release.publicKey, 'kvotab.other', '0.1.6', 'a'.repeat(64), s0),
  U.verifyRelease(release.publicKey, ID, '0.1.6', 'a'.repeat(64), 'not base64 at all')
], [true, false, false, false, false, false]);
check('  and is 88 characters of base64, as checkNewNote wants', /^[A-Za-z0-9+/]{86}==$/.test(s0));
const throwsWith = (fn) => { try { fn(); return null; } catch (e) { return e.message; } };
check('a note that is not JSON, or names no version, says so',
  [throwsWith(() => U.readNote('{ broken')).startsWith('the release note is not JSON'), throwsWith(() => U.readNote('{"version": "1.2"}')), throwsWith(() => U.readNote('"0.1.6"'))],
  [true, 'the release note names no version', 'the release note names no version']);

/* ── looking when asked ───────────────────────────────────────────────── */

{
  const t = vscodeWith();
  publish('0.1.5');
  site.requests = [];
  await t.updater.check(true);
  await t.settle();
  check('asked, with the same version on the site: up to date, and nothing downloaded',
    [t.texts(), packageRequests(), t.states()], [['info: The HDF5 Browser is up to date: 0.1.5 is the latest version.'], 0, ['latest']]);
}
{
  const t = vscodeWith();
  publish('0.1.4', { drop: ['signature'] });   // as 0.1.4's note is: from before the signing
  await t.updater.check(true);
  await t.settle();
  check('an older version on the site, its note unsigned: up to date too, no complaint', t.texts(), ['info: The HDF5 Browser is up to date: 0.1.5 is the latest version.']);
}
{
  const t = vscodeWith({ answer: (text, buttons) => (buttons.includes('Reload Window') ? 'Reload Window' : undefined) });
  const bytes = publish('0.1.6');
  site.requests = [];
  await t.updater.check(true);
  await t.settle();
  check('asked, a newer version is installed: the package VS Code is handed is the one released',
    [t.installed.length, t.installed.length && t.installed[0].bytes.equals(bytes)], [1, true]);
  check('  with the progress in a notification', t.progress, [15]);
  check('  then the window is offered a reload, and reloaded when that is chosen',
    [t.texts(), t.ran], [['info: HDF5 Browser 0.1.6 is installed. Reload the window to start it.'], ['workbench.extensions.installExtension', 'workbench.action.reloadWindow']]);
  check('  the downloaded file and the lock are gone afterwards', fs.readdirSync(t.context.globalStorageUri.fsPath), []);
  check('  and the package was asked for as that version\'s', site.requests.filter(r => r.startsWith('/dist/hdf5-browser.vsix')), ['/dist/hdf5-browser.vsix?v=0.1.6']);
  check('  and the note with a query that no cache on the way has answered before', /^\/dist\/latest\.json\?t=\d+$/.test(site.requests[0]));
}

/* ── looking by itself ────────────────────────────────────────────────── */

{
  const t = vscodeWith();
  publish('0.1.6');
  site.requests = [];
  const before = Date.now();
  await t.updater.lookIfDue();
  await t.settle();
  check('by itself, in the default mode, a newer version is installed, the progress in the status bar',
    [t.installed.length, t.progress, t.states()], [1, [10], ['installed']]);
  check('  and the window is offered a reload', t.texts(), ['info: HDF5 Browser 0.1.6 is installed. Reload the window to start it.']);
  check('  and when it looked is kept for every window', t.state.get(U.LAST_LOOK_KEY) >= before);
  site.requests = [];
  await t.updater.lookIfDue();
  await t.settle();
  check('a look soon after is not made at all', noteRequests(), 0);
  t.state.set(U.LAST_LOOK_KEY, Date.now() - U.LOOK_EVERY_MS - 1000);
  await t.updater.lookIfDue();
  await t.settle();
  check('one when the last has grown old is', noteRequests(), 1);
  t.state.set(U.LAST_LOOK_KEY, Date.now() + 3600 * 1000);
  await t.updater.lookIfDue();
  await t.settle();
  check('  and so is one when the last is in the future (the clock was put back)', noteRequests(), 2);
}
{
  const t = vscodeWith({ settings: { 'hdf5Browser.updates': 'notify' } });
  publish('0.1.6');
  await t.updater.lookIfDue();
  await t.settle();
  check('hdf5Browser.updates notify: a newer version is offered, not installed',
    [t.said.map(m => [m.text, m.buttons]), t.installed.length], [[['HDF5 Browser 0.1.6 is out; you have 0.1.5.', ['Install', 'Not Now']]], 0]);
  t.state.clear();
  await t.updater.lookIfDue();
  await t.settle();
  check('  and offered once: the next look by itself says nothing', t.said.length, 1);
}
{
  let chosen = 0;
  const t = vscodeWith({ settings: { 'hdf5Browser.updates': 'notify' }, answer: (text, buttons) => (buttons.includes('Install') && !chosen++ ? 'Install' : undefined) });
  const bytes = publish('0.1.6');
  await t.updater.check(true);
  await t.settle();
  check('  Install chosen: installed, the progress in a notification',
    [t.installed.length && t.installed[0].bytes.equals(bytes), t.progress, t.texts().at(-1)],
    [true, [15], 'info: HDF5 Browser 0.1.6 is installed. Reload the window to start it.']);
}
{
  const t = vscodeWith({ settings: { 'hdf5Browser.updates': 'notify' } });
  publish('0.1.6');
  const look = t.updater.check(true);
  let settled = false;
  look.then(() => { settled = true; });
  await new Promise(resolve => setTimeout(resolve, 200));
  check('  an offer left open does not hold up the look (the command stays free)', [settled, t.updater.busy], [true, null]);
}
for (const [auto, label] of [[false, 'false'], ['off', 'off'], ['onlySelectedExtensions', 'onlySelectedExtensions']]) {
  const t = vscodeWith({ settings: { 'extensions.autoUpdate': auto } });
  publish('0.1.6');
  await t.updater.lookIfDue();
  await t.settle();
  check(`VS Code's extensions.autoUpdate ${label}: offered rather than installed`, [t.installed.length, t.states()], [0, ['offered']]);
}
{
  const t = vscodeWith({ settings: { 'extensions.autoCheckUpdates': false } });
  publish('0.1.6');
  site.requests = [];
  await t.updater.lookIfDue();
  check('VS Code\'s extensions.autoCheckUpdates off: no look by itself', noteRequests(), 0);
  await t.updater.check(true);
  await t.settle();
  check('  asked, it looks, and offers', [noteRequests(), t.states()], [1, ['offered']]);
}
{
  const t = vscodeWith({ settings: { 'hdf5Browser.updates': 'off' } });
  publish('0.1.6');
  site.requests = [];
  await t.updater.lookIfDue();
  check('hdf5Browser.updates off: no look by itself', noteRequests(), 0);
  await t.updater.check(true);
  await t.settle();
  check('  asked, a newer version is offered, not installed at once', [t.states(), t.installed.length], [['offered'], 0]);
}
{
  const t = vscodeWith();
  publish('0.1.6');
  site.requests = [];
  await Promise.all([t.updater.check(true), t.updater.check(true), t.updater.lookIfDue()]);
  await t.settle();
  check('looks at once are one look, and one install', [noteRequests(), t.installed.length], [1, 1]);
}

/* ── what is refused ──────────────────────────────────────────────────── */

async function refusedCase(label, arrange, { want, downloads = 0 }) {
  const t = vscodeWith();
  arrange();
  site.requests = [];
  await t.updater.lookIfDue();
  await t.settle();
  check(`${label}: not installed`, [t.installed.length, t.states(), packageRequests()], [0, ['refused'], downloads]);
  check('  said, with no way to the site: the one package not to install by hand',
    t.said.map(m => [m.kind, m.text, m.buttons]), [['warning', `HDF5 Browser ${site.note.version} was not installed: ${want}.`, ['Show Log']]]);
  t.state.clear();
  await t.updater.lookIfDue();
  await t.settle();
  check('  and said once, of what it found by itself', t.said.length, 1);
  return t;
}
await refusedCase('a release signed with another key', () => publish('0.1.6', { key: stranger.privateKey }),
  { want: 'its release note is not signed with the release key' });
await refusedCase('an older release\'s signature on a note of a newer version', () => publish('0.1.7', { signedVersion: '0.1.6' }),
  { want: 'its release note is not signed with the release key' });
await refusedCase('a note of a newer version without a signature', () => publish('0.1.6', { drop: ['signature'] }),
  { want: 'the release note is not signed' });
await refusedCase('a note without the package\'s hash', () => publish('0.1.6', { drop: ['sha256'] }),
  { want: 'the release note gives no SHA-256 of the package' });
await refusedCase('a package not the one the note names (the same size)', () => {
  publish('0.1.6');
  site.pkg = crypto.randomBytes(site.pkg.length);
}, { want: 'the package is not the one its release note names: its SHA-256 differs', downloads: 1 });
await refusedCase('a package larger than the note says', () => {
  publish('0.1.6');
  site.pkg = Buffer.concat([site.pkg, Buffer.from('more')]);
}, { want: 'the package is larger than its release note says', downloads: 1 });

{
  const t = vscodeWith();
  publish('0.1.6');
  site.pkg = site.pkg.subarray(0, 1000);
  await t.updater.check(true);
  await t.settle();
  check('a package that comes short fails (the network, not a forgery): an error, with the site to get it from',
    t.said.map(m => [m.kind, m.text, m.buttons]),
    [['error', `Could not install HDF5 Browser 0.1.6: the package came to 1000 bytes, and its release note says 3000`, ['Download from kvotab.se', 'Show Log']]]);
}
{
  const t = vscodeWith();
  publish('0.1.6', { vscode: '^1.200.0' });
  await t.updater.check(true);
  await t.settle();
  check('a version for a newer VS Code: said, and nothing downloaded', [t.texts(), packageRequests() && t.installed.length],
    [['warning: HDF5 Browser 0.1.6 needs VS Code 1.200.0 or later, and this is 1.135.0: update VS Code to have it.'], 0]);
}

/* ── when the site cannot be read ─────────────────────────────────────── */

{
  const t = vscodeWith();
  site.note = null;
  await t.updater.lookIfDue();
  await t.settle();
  check('no note (404), by itself: nothing said, the log says why', [t.said.length, t.logs.some(l => l.includes('the release note: HTTP 404'))], [0, true]);
  await t.updater.check(true);
  await t.settle();
  check('  asked: said, with the site to try instead', t.said.map(m => [m.kind, m.text, m.buttons]),
    [['error', 'Could not look for an update of the HDF5 Browser: the release note: HTTP 404', ['Download from kvotab.se', 'Show Log']]]);
}
{
  const t = vscodeWith();
  site.note = '{ "version": ';
  await t.updater.check(true);
  await t.settle();
  check('a note that is not JSON, asked', t.said[0].text.startsWith('Could not look for an update of the HDF5 Browser: the release note is not JSON'));
}
{
  const t = vscodeWith();
  const closed = http.createServer();
  await new Promise(resolve => closed.listen(0, '127.0.0.1', resolve));
  const port = closed.address().port;
  await new Promise(resolve => closed.close(resolve));
  t.updater.releases = `http://127.0.0.1:${port}/dist/`;
  await t.updater.check(true);
  await t.settle();
  check('no site at all, asked: the reason is the connection\'s', /the release note: connect ECONNREFUSED/.test(t.said[0] && t.said[0].text), true);
}

/* ── installed already, other windows, development ────────────────────── */

{
  const t = vscodeWith({ answer: (text, buttons) => (buttons.includes('Reload Window') ? 'Reload Window' : undefined) });
  publish('0.1.6');
  const next = path.join(t.extensions, `${ID}-0.1.6`);
  fs.mkdirSync(next);
  fs.writeFileSync(path.join(next, 'package.json'), JSON.stringify({ version: '0.1.6' }));
  site.requests = [];
  await t.updater.check(true);
  await t.settle();
  check('a version installed already (by another window): a reload is offered, nothing downloaded',
    [t.texts(), packageRequests(), t.ran], [['info: HDF5 Browser 0.1.6 is installed. Reload the window to start it.'], 0, ['workbench.action.reloadWindow']]);
  fs.writeFileSync(path.join(t.extensions, '.obsolete'), JSON.stringify({ [`${ID}-0.1.6`]: true }));
  await t.updater.check(true);
  await t.settle();
  check('  one VS Code is to remove (.obsolete) is installed again', t.installed.length, 1);
}
{
  const t = vscodeWith();
  publish('0.1.6');
  fs.mkdirSync(t.context.globalStorageUri.fsPath, { recursive: true });
  const lock = path.join(t.context.globalStorageUri.fsPath, 'update.lock');
  fs.writeFileSync(lock, '1');
  await t.updater.check(true);
  await t.settle();
  check('another window installing (its lock): not installed here too', [t.installed.length, t.texts()],
    [0, ['info: Another VS Code window is installing HDF5 Browser 0.1.6.']]);
  const old = (Date.now() - 11 * 60 * 1000) / 1000;
  fs.utimesSync(lock, old, old);
  await t.updater.check(true);
  await t.settle();
  check('  a lock left by a window that went away (10 minutes old) is taken over', [t.installed.length, fs.existsSync(lock)], [1, false]);
}
{
  const t = vscodeWith({ installFails: 'Unable to install the extension: not allowed by extensions.allowed' });
  publish('0.1.6');
  await t.updater.check(true);
  await t.settle();
  check('VS Code refusing the install: said, with the site to get it from',
    t.said.map(m => [m.kind, m.text, m.buttons]),
    [['error', 'Could not install HDF5 Browser 0.1.6: Unable to install the extension: not allowed by extensions.allowed', ['Download from kvotab.se', 'Show Log']]]);
  check('  the downloaded file and the lock are gone', fs.readdirSync(t.context.globalStorageUri.fsPath), []);
}
{
  const t = vscodeWith({ mode: 2 });
  publish('0.1.6');
  site.requests = [];
  await t.updater.check(true);
  await t.settle();
  check('a copy run from its folder (development) is not updated, and says so', [t.texts(), packageRequests()],
    [['info: HDF5 Browser 0.1.6 is out. This copy runs from its folder, not installed, so it is not updated.'], 0]);
}

/* ── the key ──────────────────────────────────────────────────────────── */

{
  const t = vscodeWith();
  const u = new U.Updater({ vscode: t.vscode, context: t.context, log: t.log, releases: BASE });
  check('the key the extension carries (src/release-public-key.pem) loads', [u.keyError, u.publicKey && u.publicKey.asymmetricKeyType], [null, 'ed25519']);
  process.env.KVOT_HDF5_UPDATE_KEY = 'not a key';
  const broken = new U.Updater({ vscode: t.vscode, context: t.context, log: t.log, releases: BASE });
  delete process.env.KVOT_HDF5_UPDATE_KEY;
  publish('0.1.6');
  await broken.check(true);
  await t.settle();
  check('  without one, a look says it cannot check a release', t.said[0] && t.said[0].text.startsWith('Could not look for an update of the HDF5 Browser: this copy has no key'), true);
}

/* ── release.mjs's key checks (they come before any build) ────────────── */

function release_(args, env) {
  try {
    execFileSync('node', ['release.mjs', ...args], { cwd: EXTENSION, env: Object.assign({}, process.env, env), stdio: 'pipe' });
    return { status: 0, err: '' };
  } catch (e) {
    return { status: e.status, err: String(e.stderr) };
  }
}
{
  const missing = path.join(temp, 'missing.pem');
  let r = release_(['--no-build'], { RB_VSCODE_RELEASE_KEY: missing });
  check('release.mjs without the private key refuses to release', [r.status, r.err.includes(`no release key at ${missing}`)], [1, true]);
  const wrong = path.join(temp, 'wrong.pem');
  fs.writeFileSync(wrong, stranger.privateKey.export({ type: 'pkcs8', format: 'pem' }));
  r = release_(['--no-build'], { RB_VSCODE_RELEASE_KEY: wrong });
  check('  and with a key the extension does not check with', [r.status, r.err.includes('is not the key src/release-public-key.pem checks with')], [1, true]);
  r = release_(['--new-key'], { RB_VSCODE_RELEASE_KEY: path.join(temp, 'new.pem') });
  check('  --new-key leaves the extension\'s key alone when it has one', [r.status, r.err.includes('has a release key already'), fs.existsSync(path.join(temp, 'new.pem'))], [1, true, false]);
}

server.close();
fs.rmSync(temp, { recursive: true, force: true });
console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log(`failed: ${failures.join(', ')}`);
process.exit(failures.length ? 1 : 0);
