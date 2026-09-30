#!/usr/bin/env node
/* ==========================================================================
   RELEASE THE HDF5 BROWSER EXTENSION

   node release.mjs [--no-build] [--force]
   node release.mjs --new-key | --replace-key

   Builds the extension (build.mjs), packages it with vsce, and puts the
   package where the site hands it out: dist/hdf5-browser.vsix, with
   dist/latest.json saying which version it is. Commit dist/ and push, and
   the VS Code button on kvotab.se/rb.html offers it; the page reads
   latest.json when the dialog opens, so it needs no change of its own. The
   installed copies read latest.json too (src/update.js), and install the
   new version by themselves.

   They install it only if the note's signature verifies with the public key
   they carry, src/release-public-key.pem. The signature is made here, with
   the private key, which is never in the repository: RB_VSCODE_RELEASE_KEY
   names it, or it is ~/.config/kvotab/hdf5-browser-release-key.pem. Keep a
   copy of it somewhere safe. --new-key makes the pair once; --replace-key
   makes a new one, and then every copy installed before has to be updated
   by hand once (from the site), since it checks with the old key.

   A version is released once. A second build of the same version installed
   over the first is written into the same folder while VS Code goes on
   running the old one, which then serves a page from the new files (see
   webview/early.js); a new version is installed beside the old and VS Code
   asks for the reload. So bump "version" in package.json first; --force
   replaces a release of the same version anyway.

   The package is committed, so every release adds its size (some 4.5 MB)
   to the repository's history.
   ========================================================================== */

import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.join(HERE, 'dist');
const LATEST = path.join(DIST, 'latest.json');
const PACKAGE = path.join(DIST, 'hdf5-browser.vsix');   // the page and the installed copies fetch this name
const PUBLIC_KEY = path.join(HERE, 'src', 'release-public-key.pem');
const PRIVATE_KEY = process.env.RB_VSCODE_RELEASE_KEY
  || path.join(os.homedir(), '.config', 'kvotab', 'hdf5-browser-release-key.pem');
// What is signed, and how it is checked, is the updater's own.
const { signRelease, verifyRelease } = createRequire(import.meta.url)('./src/update.js');

function fail(message) {
  console.error(`release.mjs: ${message}`);
  process.exit(1);
}

function run(cmd, args) {
  console.log(`> ${cmd} ${args.join(' ')}`);
  execFileSync(cmd, args, { cwd: HERE, stdio: 'inherit' });
}

const args = new Set(process.argv.slice(2));
for (const a of args) if (!['--no-build', '--force', '--new-key', '--replace-key'].includes(a)) fail(`unknown option ${a}`);

/** A new key pair: the private key where release.mjs looks for it, the public one in the extension. */
function newKey(replace) {
  if (fs.existsSync(PRIVATE_KEY)) fail(`${PRIVATE_KEY} exists already; it is left as it is.`);
  if (fs.existsSync(PUBLIC_KEY) && !replace) {
    fail('the extension has a release key already (src/release-public-key.pem). --replace-key replaces it, '
      + 'and every copy installed before then has to be updated by hand once.');
  }
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519', {
    publicKeyEncoding: { type: 'spki', format: 'pem' },
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' }
  });
  fs.mkdirSync(path.dirname(PRIVATE_KEY), { recursive: true, mode: 0o700 });
  fs.writeFileSync(PRIVATE_KEY, privateKey, { mode: 0o600, flag: 'wx' });
  fs.writeFileSync(PUBLIC_KEY, publicKey);
  console.log(`made a release key:\n  private: ${PRIVATE_KEY} (keep a copy of it somewhere safe; never commit it)`
    + `\n  public:  ${path.relative(process.cwd(), PUBLIC_KEY)} (commit it: the next version carries it)`);
  process.exit(0);
}
if (args.has('--new-key') || args.has('--replace-key')) newKey(args.has('--replace-key'));

/** The private key, if it is the one the extension checks with. */
function releaseKey() {
  if (!fs.existsSync(PUBLIC_KEY)) fail('the extension has no release key (src/release-public-key.pem): node release.mjs --new-key makes one.');
  if (!fs.existsSync(PRIVATE_KEY)) {
    fail(`no release key at ${PRIVATE_KEY}. Copy it there from where it is kept (or name it in RB_VSCODE_RELEASE_KEY); `
      + 'without it, the installed copies will not take the release.');
  }
  const privateKey = crypto.createPrivateKey(fs.readFileSync(PRIVATE_KEY));
  const publicKey = crypto.createPublicKey(fs.readFileSync(PUBLIC_KEY));
  const der = k => k.export({ type: 'spki', format: 'der' });
  if (!der(crypto.createPublicKey(privateKey)).equals(der(publicKey))) {
    fail(`${PRIVATE_KEY} is not the key src/release-public-key.pem checks with: the installed copies would not take this release.`);
  }
  return { privateKey, publicKey };
}
const key = releaseKey();

const pkg = JSON.parse(fs.readFileSync(path.join(HERE, 'package.json'), 'utf8'));
if (!/^\d+\.\d+\.\d+$/.test(pkg.version)) fail(`package.json's version ${pkg.version} is not x.y.z`);
const prior = fs.existsSync(LATEST) ? JSON.parse(fs.readFileSync(LATEST, 'utf8')) : null;
if (prior && prior.version === pkg.version && !args.has('--force')) {
  fail(`${pkg.version} is released already (dist/latest.json). Bump "version" in package.json first, `
    + 'or pass --force to replace that release.');
}

if (!args.has('--no-build')) run('node', ['build.mjs']);
const out = path.join(HERE, `${pkg.name}-${pkg.version}.vsix`);
run('npx', ['--no-install', 'vsce', 'package', '--out', out]);

fs.mkdirSync(DIST, { recursive: true });
fs.copyFileSync(out, PACKAGE);
const bytes = fs.readFileSync(PACKAGE);
const build = JSON.parse(fs.readFileSync(path.join(HERE, 'media', 'build.json'), 'utf8'));
const id = `${pkg.publisher}.${pkg.name}`.toLowerCase();
const sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
const signature = signRelease(key.privateKey, id, pkg.version, sha256);
if (!verifyRelease(key.publicKey, id, pkg.version, sha256, signature)) fail('the signature made does not verify');
const latest = {
  name: pkg.displayName,
  version: pkg.version,
  file: path.basename(PACKAGE),
  bytes: bytes.length,
  sha256,
  released: new Date().toISOString(),
  build: build.stamp,
  vscode: pkg.engines.vscode,
  signature
};
fs.writeFileSync(LATEST, JSON.stringify(latest, null, 2) + '\n');

console.log(`\nreleased ${pkg.version}: dist/${latest.file} (${(bytes.length / 1048576).toFixed(1)} MB, page build ${build.stamp})`);
if (build.dirty) console.log('note: built from a checkout with uncommitted changes (the build stamp ends in +)');
console.log('next: git add rb-vscode/dist && git commit, then push; the site offers it from the VS Code button, '
  + 'and the copies installed (0.1.5 and later) update to it by themselves');
