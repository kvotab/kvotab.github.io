#!/usr/bin/env node
/* ==========================================================================
   BUILD: rb.html INTO A VS CODE WEBVIEW

       node build.mjs

   Writes media/ (the page, as the webview gets it) and node/ (h5wasm's Node
   build, for the reader) from the site's own files, so the extension shows
   exactly what kvotab.se shows. Nothing here is edited by hand; run it again
   after a change to rb.html or its scripts.

   What it does to the page, and nothing more:
     * every script and stylesheet is served from the extension, the CDN ones
       from copies that must match the hashes rb.html pins (the page keeps its
       integrity attributes, so the browser checks them again);
     * the three inline scripts become files, since the webview's policy runs
       no inline script: the Excel flag as it is; the header as the file
       toolbar alone (no logo, no page name, no navigation, footer or map) with
       a light/dark toggle; the theme one is dropped, because early.js themes;
     * the URL and Sample Data buttons go, and so does the welcome text that
       names them;
     * the workers the page starts are bundled as source, which is how
       webview/early.js starts them.

   It refuses to build, rather than guess, when rb.html no longer looks as
   described here, when a pinned file does not match its hash, when a script
   names a CDN file that is not bundled, or when rb-lazy-worker.js has changed
   since src/reader.mjs was last compared with it.
   ========================================================================== */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const MEDIA = path.join(HERE, 'media');
const NODE_OUT = path.join(HERE, 'node');
const CACHE = path.join(HERE, '.cache');

/*
  rb-lazy-worker.js as it was when src/reader.mjs was last checked against it
  (test/test-reader.py). If the worker's answers change, the reader's must
  change with them: compare, then put the new hash here.
*/
const READER_MIRRORS = {
  'resources/js/rb-lazy-worker.js': 'sha256-i9o8c5+25g1xtqWAcQnHF3c5YuISMxIHIHSXYetAepc='
};

/* Files the site does not load but the extension ships, pinned here. */
const EXTRA = [
  { url: 'https://cdn.jsdelivr.net/npm/h5wasm@0.10.3/dist/node/hdf5_hl.js', to: 'node/h5wasm/hdf5_hl.js',
    integrity: 'sha384-QKBAPPTKU9XHH3lAoW5hl4rfG/HPYTKR/DL0ACyi7nPmCt/GnloB2C6tDRZg/41x' },
  { url: 'https://cdn.jsdelivr.net/npm/h5wasm@0.10.3/dist/node/hdf5_util.js', to: 'node/h5wasm/hdf5_util.js',
    integrity: 'sha384-AVanQsMzkodQFWEOGoE6PzX1XzHnUG4IbSjwE8Om6l1Lckxmx9NMKL1JP6wue6by' }
];

/* The welcome panel's first step names the URL button; here it names the Explorer. */
const WELCOME_LOAD = '<li><strong>Load files</strong> — drag &amp; drop <code>.h5</code> / <code>.hdf5</code> files onto the page, click <em>Add Files</em>, or use <em>URL</em> to fetch from a remote server.</li>';
const WELCOME_LOAD_VSCODE = '<li><strong>Load files</strong> — open an <code>.h5</code> / <code>.hdf5</code> file from the Explorer, or click <em>Add Files</em>. To compare files, select them in the Explorer and choose <em>Open Together in HDF5 Browser</em>.</li>';

const CDN = /^https:\/\/(cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|cdn\.plot\.ly)\//;

/* ── small tools ──────────────────────────────────────────────────────── */

function fail(message) {
  console.error(`\nbuild.mjs: ${message}\n`);
  process.exit(1);
}

function sri(bytes, algorithm = 'sha384') {
  return `${algorithm}-${crypto.createHash(algorithm).update(bytes).digest('base64')}`;
}

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel));
}

function write(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
}

function once(text, find, replace, what) {
  const n = text.split(find).length - 1;
  if (n !== 1) fail(`${what}: expected the text once, found it ${n} times. Has the page changed?`);
  return text.replace(find, () => replace);
}

function attr(tag, name) {
  const m = tag.match(new RegExp(`\\s${name}\\s*=\\s*"([^"]*)"`, 'i'));
  return m ? m[1] : null;
}

/** A pinned file: from the cache, from the repo's own copy, or downloaded; always checked. */
async function pinned(url, integrity) {
  const algorithm = integrity.split('-')[0];
  const cached = path.join(CACHE, url.replace(/^https:\/\//, ''));
  const candidates = [cached];
  // Plotly is in the repo already (vendors/js), byte for byte the CDN's.
  candidates.push(path.join(ROOT, 'vendors', 'js', path.basename(url)));
  for (const file of candidates) {
    if (fs.existsSync(file)) {
      const bytes = fs.readFileSync(file);
      if (sri(bytes, algorithm) === integrity) return bytes;
    }
  }
  process.stdout.write(`  downloading ${url}\n`);
  const response = await fetch(url);
  if (!response.ok) fail(`${url}: HTTP ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  const got = sri(bytes, algorithm);
  if (got !== integrity) fail(`${url} does not match its pin: got ${got}, expected ${integrity}`);
  write(cached, bytes);
  return bytes;
}

function vendorPath(url) {
  return path.join(MEDIA, 'vendor', url.replace(/^https:\/\//, '').split(/[?#]/)[0]);
}

function local(src) {
  return src.replace(/^\.\//, '').split(/[?#]/)[0];
}

/* ── the page ─────────────────────────────────────────────────────────── */

async function main() {
  const html = read('rb.html').toString('utf8');
  fs.rmSync(MEDIA, { recursive: true, force: true });
  fs.rmSync(NODE_OUT, { recursive: true, force: true });

  // Every mirror still what the reader was compared with.
  for (const [rel, pin] of Object.entries(READER_MIRRORS)) {
    const got = sri(read(rel), 'sha256');
    if (got !== pin) {
      fail(`${rel} has changed since src/reader.mjs was compared with it (now ${got}).\n`
        + 'Run test/test-reader.py; when the reader answers as the worker does, put the new hash in READER_MIRRORS.');
    }
  }

  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)].map(m => ({
    tag: m[0], attrs: m[1], body: m[2], src: attr(m[0], 'src'), integrity: attr(m[0], 'integrity')
  }));
  const inline = scripts.filter(s => !s.src);
  const xlsxFlag = inline.filter(s => s.body.includes('window.xlsxReady'));
  const themeBoot = inline.filter(s => s.body.includes("localStorage.getItem('kvot-theme')"));
  const header = inline.filter(s => s.body.includes('KVOT.renderHeader'));
  if (inline.length !== 3 || xlsxFlag.length !== 1 || themeBoot.length !== 1 || header.length !== 1) {
    fail(`rb.html has ${inline.length} inline scripts; expected exactly the Excel flag, the theme and the header.`);
  }

  // The header as it is, less what belongs to the site.
  // The extension's own download (VS Code) is no use inside it, either.
  const siteButtons = /\n[ \t]*<button[^>]*data-on-click="(openUrlDialog|openSampleDataDialog|openVscodeDialog)"[\s\S]*?<\/button>/g;
  const found = (header[0].body.match(siteButtons) || []).length;
  if (found !== 3) fail(`expected the URL, Sample Data and VS Code buttons in the header, found ${found}`);
  let headerJs = header[0].body.replace(siteButtons, '');
  for (const drop of ["KVOT.renderNav('rb.html');", 'KVOT.renderFooter();', "KVOT.initMap('kvotmap');"]) {
    headerJs = once(headerJs, drop, '', `the header script's ${drop}`);
  }
  // The light/dark toggle, right of Add Files: the site has one in its footer,
  // which is not built in (webview/early.js does the switching).
  const addFiles = '<button class="add-file-btn" data-on-click="openFilePicker">Add Files</button>';
  headerJs = once(headerJs, addFiles, `${addFiles}
        <button class="rb-theme-toggle" data-on-click="vscode:toggleTheme" title="Switch between light and dark" aria-label="Switch between light and dark"><span class="rb-ico" aria-hidden="true"></span></button>`,
  'the Add Files button in the header script');
  // The header is the file toolbar alone, without the logo and the page's
  // name: VS Code's editor tab names the file already, and the file tabs get
  // the width. rb-vscode.css lays it out.
  headerJs = once(headerJs, "KVOT.renderHeader('HDF5 Browser', fileToolbar);", `{
      const header = document.querySelector('header');
      header.classList.add('rb-vscode-header');
      header.innerHTML = fileToolbar;
    }`, 'the header script\'s KVOT.renderHeader');

  const generated = {
    'rb-vscode/xlsx-flag.js': `/* Generated by build.mjs from rb.html's inline script. */\n${xlsxFlag[0].body.trim()}\n`,
    'rb-vscode/header.js': '/* Generated by build.mjs from rb.html\'s inline script: the file toolbar alone, without the '
      + 'site\'s logo, name, navigation, footer, map, URL, Sample Data and VS Code buttons, and with a light/dark toggle. */\n'
      + `'use strict';\n${headerJs.trim()}\n`
  };

  const vendored = [];      // { url, file }
  const copied = new Set(); // repo-relative paths copied into media/
  let page = html;

  for (const s of scripts) {
    let replacement;
    if (s === themeBoot[0]) {
      replacement = '';
    } else if (s === xlsxFlag[0]) {
      replacement = '<script src="{{MEDIA}}/rb-vscode/xlsx-flag.js"></script>';
    } else if (s === header[0]) {
      replacement = '<script src="{{MEDIA}}/rb-vscode/header.js"></script>';
    } else if (CDN.test(s.src)) {
      if (!s.integrity) fail(`${s.src} is loaded from a CDN without an integrity pin`);
      vendored.push({ url: s.src, integrity: s.integrity });
      const rel = path.relative(MEDIA, vendorPath(s.src)).split(path.sep).join('/');
      replacement = s.tag.replace(s.src, `{{MEDIA}}/${rel}`);
    } else if (/^\.?\/?resources\//.test(s.src)) {
      copied.add(local(s.src));
      replacement = s.tag.replace(s.src, `{{MEDIA}}/${local(s.src)}`);
    } else {
      fail(`a script from ${s.src} is neither bundled nor the site's own`);
    }
    page = once(page, s.tag, replacement, `the script ${s.src || 'inline'}`);
  }

  const styles = [...html.matchAll(/<link\b[^>]*rel="stylesheet"[^>]*>/gi)].map(m => m[0]);
  if (styles.length !== 2) fail(`expected rb.html's two stylesheets, found ${styles.length}`);
  for (const tag of styles) {
    const href = attr(tag, 'href');
    copied.add(local(href));
    page = once(page, tag, `<link rel="stylesheet" href="{{MEDIA}}/${local(href)}">`, `the stylesheet ${href}`);
  }

  // The head: this page's policy and settings, then the page's own, less the site's.
  const head = page.match(/<head>([\s\S]*?)<\/head>/i);
  if (!head) fail('rb.html has no <head>');
  const keep = head[1]
    .replace(/<!--[\s\S]*?-->/g, '')
    .split('\n')
    .filter(line => /<script|<link rel="stylesheet"/.test(line))
    .map(line => line.trim())
    .filter(Boolean);
  page = page.replace(head[0], [
    '<head>',
    '  <meta charset="utf-8" />',
    '  <meta name="viewport" content="width=device-width,initial-scale=1"/>',
    '  <meta http-equiv="Content-Security-Policy" content="{{CSP}}">',
    '  <meta name="kvot-vscode" content="{{CONFIG}}">',
    '  <title>HDF5 Browser</title>',
    '  <script src="{{MEDIA}}/rb-vscode/codec.js"></script>',
    '  <script src="{{MEDIA}}/rb-vscode/early.js"></script>',
    '  <script src="{{MEDIA}}/rb-vscode/workers.js"></script>',
    ...keep.map(line => `  ${line}`),
    '  <link rel="stylesheet" href="{{MEDIA}}/rb-vscode/rb-vscode.css">',
    '</head>'
  ].join('\n'));
  page = page.replace(/<html lang="en">/, '<html lang="en" data-theme="{{THEME}}" data-theme-default="{{THEME}}">');
  if (!page.includes('data-theme="{{THEME}}"')) fail('rb.html\'s <html lang="en"> tag has changed');

  page = once(page, '<div id="kvotmap"></div>', '', 'the site map element');
  page = once(page, '<footer></footer>', '', 'the footer element');
  page = once(page, WELCOME_LOAD, WELCOME_LOAD_VSCODE, 'the welcome panel\'s first step in rb.html');
  page = once(page, '</body>', '  <script src="{{MEDIA}}/rb-vscode/late.js"></script>\n</body>', 'the end of the body');

  if (/<script(?![^>]*\ssrc=)[^>]*>/i.test(page)) fail('an inline script is left in the page');
  if (/\son[a-z]+\s*=\s*"/i.test(page)) fail('an inline event handler is in the page; the webview\'s policy would refuse it');

  /* ── the page's own files, and what they name ─────────────────────── */

  const sources = {};
  for (const rel of [...copied]) {
    let bytes = read(rel);
    if (rel === 'resources/js/rb-state.js') {
      bytes = Buffer.from(once(bytes.toString('utf8'), WELCOME_LOAD, WELCOME_LOAD_VSCODE, 'the welcome panel\'s first step in rb-state.js'));
    }
    write(path.join(MEDIA, rel), bytes);
    if (rel.endsWith('.js')) sources[rel] = bytes.toString('utf8');
    if (rel.endsWith('.css')) {
      for (const m of bytes.toString('utf8').matchAll(/url\(\s*['"]?(?!data:)([^'")]+)['"]?\s*\)/g)) {
        const dep = path.posix.normalize(path.posix.join(path.posix.dirname(rel), m[1]));
        write(path.join(MEDIA, dep), read(dep));
      }
    }
  }

  // The workers the scripts start, bundled as source for webview/early.js.
  const workers = {};
  for (const [rel, text] of Object.entries(sources)) {
    for (const m of text.matchAll(/new Worker\(\s*['"]([^'"]+)['"]/g)) {
      const wrel = local(m[1]);
      if (!fs.existsSync(path.join(ROOT, wrel))) fail(`${rel} starts a worker ${m[1]} that is not in the repo`);
      workers[wrel] = read(wrel).toString('utf8');
    }
  }
  if (!workers['resources/js/rb-lazy-worker.js'] || !workers['resources/js/tree-worker.js']) {
    fail(`expected the lazy-file and tree workers, found ${Object.keys(workers).join(', ') || 'none'}`);
  }
  generated['rb-vscode/workers.js'] = '/* Generated by build.mjs: the workers the page starts, as source (see early.js). */\n'
    + `self.KVOT_VSCODE_WORKER_SOURCES = ${JSON.stringify(workers)};\n`;
  for (const [rel, text] of Object.entries(workers)) {
    sources[rel] = text;
    write(path.join(MEDIA, rel), text);
  }

  // The compression plugins: rb-lazy.js's list, which the lazy worker must repeat exactly.
  const lazyJs = sources['resources/js/rb-lazy.js'];
  const pluginBase = (lazyJs.match(/RB_PLUGIN_BASE\s*=\s*'([^']+)'/) || [])[1];
  const pluginPins = Object.fromEntries([...(lazyJs.match(/RB_PLUGIN_INTEGRITY\s*=\s*Object\.freeze\(\{([\s\S]*?)\}\)/) || ['', ''])[1]
    .matchAll(/(\w+):\s*'(sha384-[^']+)'/g)].map(m => [m[1], m[2]]));
  const workerJs = workers['resources/js/rb-lazy-worker.js'];
  const workerBase = (workerJs.match(/PLUGIN_BASE\s*=\s*'([^']+)'/) || [])[1];
  const workerPins = Object.fromEntries([...(workerJs.match(/PLUGIN_INTEGRITY\s*=\s*\{([\s\S]*?)\}/) || ['', ''])[1]
    .matchAll(/(\w+):\s*'(sha384-[^']+)'/g)].map(m => [m[1], m[2]]));
  if (!pluginBase || Object.keys(pluginPins).length < 5) fail('could not read the plugin list from rb-lazy.js');
  if (pluginBase !== workerBase || JSON.stringify(pluginPins) !== JSON.stringify(workerPins)) {
    fail('rb-lazy.js and rb-lazy-worker.js no longer pin the same compression plugins');
  }
  for (const [name, integrity] of Object.entries(pluginPins)) vendored.push({ url: `${pluginBase}libH5Z${name}.so`, integrity });

  // Every h5wasm the scripts fetch must be the one the page's <script> pins.
  const h5wasmTag = vendored.find(v => /\/h5wasm@[^/]+\/dist\/iife\/h5wasm\.min\.js$/.test(v.url));
  if (!h5wasmTag) fail('rb.html no longer loads h5wasm from the CDN');
  for (const [rel, text] of Object.entries(sources)) {
    for (const m of text.matchAll(/https:\/\/cdn\.jsdelivr\.net\/npm\/h5wasm@[^'"`\s]+h5wasm\.min\.js/g)) {
      if (m[0] !== h5wasmTag.url) fail(`${rel} fetches ${m[0]}, not the page's ${h5wasmTag.url}`);
      if (!text.includes(h5wasmTag.integrity)) fail(`${rel} fetches h5wasm without the page's pin`);
    }
  }

  for (const v of vendored) write(vendorPath(v.url), await pinned(v.url, v.integrity));
  for (const x of EXTRA) write(path.join(HERE, x.to), await pinned(x.url, x.integrity));
  // h5wasm's Node build is ES modules in .js files, as its own package.json
  // declares. Node 22 and later guess that from the syntax; Node 20, which
  // older VS Code runs extensions on, loads them as CommonJS and fails.
  write(path.join(NODE_OUT, 'h5wasm', 'package.json'), '{ "type": "module" }\n');

  // Nothing may name a CDN file that is not here: in the webview it would simply fail.
  const bundledUrls = vendored.map(v => v.url);
  for (const [rel, text] of Object.entries(sources)) {
    for (const m of text.matchAll(/https:\/\/(?:cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|cdn\.plot\.ly)\/[^'"`\s)]*/g)) {
      const url = m[0].split(/[?#]/)[0];
      if (!bundledUrls.some(b => b === url || (url.endsWith('/') && b.startsWith(url)))) {
        fail(`${rel} names ${m[0]}, which is not bundled`);
      }
    }
  }

  /* ── the extension's own page files ──────────────────────────────── */

  let commit = 'unknown';
  let dirty = false;
  try {
    commit = execFileSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: ROOT }).toString().trim();
    dirty = execFileSync('git', ['status', '--porcelain', '--', 'rb.html', 'resources/js', 'resources/css', 'rb-vscode'], { cwd: ROOT })
      .toString().split('\n').some(line => line.trim() && !/\s(rb-vscode\/(media|node|\.cache)\/)/.test(line));
  } catch (_) { /* not a git checkout */ }
  const built = new Date().toISOString();
  const stamp = `${commit}${dirty ? '+' : ''} ${built.slice(0, 16).replace('T', ' ')}`;

  write(path.join(MEDIA, 'rb-vscode', 'codec.js'), fs.readFileSync(path.join(HERE, 'src', 'codec.js')));
  for (const f of ['early.js', 'late.js', 'rb-vscode.css']) {
    let text = fs.readFileSync(path.join(HERE, 'webview', f), 'utf8');
    // early.js says which build it is, so a page can tell when the extension
    // that served it is an older one, still running from before an update.
    if (f === 'early.js') {
      for (const [key, value] of [['__RB_VSCODE_STAMP__', stamp], ['__RB_VSCODE_BUILT__', built]]) {
        if (!text.includes(key)) fail(`webview/early.js has no ${key} to fill in`);
        text = text.split(key).join(value);
      }
    }
    write(path.join(MEDIA, 'rb-vscode', f), text);
  }
  for (const [rel, text] of Object.entries(generated)) write(path.join(MEDIA, rel), text);
  // The site's own licence is the extension's.
  write(path.join(HERE, 'LICENSE'), read('LICENSE'));
  write(path.join(MEDIA, 'index.html'), page);

  write(path.join(MEDIA, 'build.json'), JSON.stringify({
    stamp,
    commit, dirty, built,
    h5wasmNodeDir: 'node/h5wasm',
    pluginDir: path.relative(HERE, vendorPath(pluginBase)).split(path.sep).join('/'),
    vendored: vendored.map(v => v.url)
  }, null, 2) + '\n');

  const size = dir => fs.readdirSync(dir, { recursive: true, withFileTypes: true })
    .filter(e => e.isFile()).reduce((n, e) => n + fs.statSync(path.join(e.parentPath || e.path, e.name)).size, 0);
  console.log(`built media/ (${(size(MEDIA) / 1048576).toFixed(1)} MB: ${copied.size} page files, `
    + `${Object.keys(workers).length} workers, ${vendored.length} vendored) and node/ `
    + `(${(size(NODE_OUT) / 1048576).toFixed(1)} MB) from ${commit}${dirty ? ' with local changes' : ''}`);
}

main().catch(e => fail(e && e.stack ? e.stack : String(e)));
