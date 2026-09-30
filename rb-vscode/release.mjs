#!/usr/bin/env node
/* ==========================================================================
   RELEASE THE HDF5 BROWSER EXTENSION

   node release.mjs [--no-build] [--force]

   Builds the extension (build.mjs), packages it with vsce, and puts the
   package where the site hands it out: dist/hdf5-browser.vsix, with
   dist/latest.json saying which version it is. Commit dist/ and push, and
   the VS Code button on kvotab.se/rb.html offers it; the page reads
   latest.json when the dialog opens, so it needs no change of its own.

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
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.join(HERE, 'dist');
const LATEST = path.join(DIST, 'latest.json');
const PACKAGE = path.join(DIST, 'hdf5-browser.vsix');   // the page links to this name

function fail(message) {
  console.error(`release.mjs: ${message}`);
  process.exit(1);
}

function run(cmd, args) {
  console.log(`> ${cmd} ${args.join(' ')}`);
  execFileSync(cmd, args, { cwd: HERE, stdio: 'inherit' });
}

const args = new Set(process.argv.slice(2));
for (const a of args) if (!['--no-build', '--force'].includes(a)) fail(`unknown option ${a}`);

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
const latest = {
  name: pkg.displayName,
  version: pkg.version,
  file: path.basename(PACKAGE),
  bytes: bytes.length,
  sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
  released: new Date().toISOString(),
  build: build.stamp,
  vscode: pkg.engines.vscode
};
fs.writeFileSync(LATEST, JSON.stringify(latest, null, 2) + '\n');

console.log(`\nreleased ${pkg.version}: dist/${latest.file} (${(bytes.length / 1048576).toFixed(1)} MB, page build ${build.stamp})`);
if (build.dirty) console.log('note: built from a checkout with uncommitted changes (the build stamp ends in +)');
console.log('next: git add rb-vscode/dist && git commit, then push; the site offers it from the VS Code button');
