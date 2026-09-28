// Every answer src/reader.mjs gives about one file, as test/test-reader.py
// compares them with rb-lazy-worker.js's:  node test/reader-answers.mjs file.h5
import { Worker } from 'node:worker_threads';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';

const require = createRequire(import.meta.url);
const canonical = require('./canonical.js');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXT = path.dirname(HERE);
const build = JSON.parse(fs.readFileSync(path.join(EXT, 'media', 'build.json'), 'utf8'));

const worker = new Worker(path.join(EXT, 'src', 'reader.mjs'), {
  workerData: { h5wasmDir: path.join(EXT, build.h5wasmNodeDir), pluginDir: path.join(EXT, build.pluginDir) }
});
let seq = 0;
const pending = new Map();
worker.on('message', (m) => {
  if (m.ready) return;
  const p = pending.get(m.id);
  pending.delete(m.id);
  if (m.err) p.reject(new Error(m.err));
  else p.resolve(m.ok);
});
const ask = (cmd, args) => new Promise((resolve, reject) => {
  const id = ++seq;
  pending.set(id, { resolve, reject });
  worker.postMessage({ id, cmd, args });
});

// The walk the page side makes too: every group, then every dataset's values.
const out = { groups: {} };
const opened = await ask('open', { file: path.resolve(process.argv[2]) });
const fid = opened.fid;
out.open = Object.assign({}, opened, { fid: 'fid' });
const queue = ['/'];
const datasets = [];
while (queue.length) {
  const g = queue.shift();
  const answer = await ask('group', { fid, path: g });
  out.groups[g] = answer;
  for (const c of answer.children || []) {
    const p = g === '/' ? `/${c.name}` : `${g}/${c.name}`;
    if (c.type === 'Group') queue.push(p);
    if (c.type === 'Dataset') datasets.push(p);
  }
}
out.values = await ask('values', { fid, paths: datasets.concat(['/does/not/exist']) });
out.close = await ask('close', { fid });
console.log(JSON.stringify(canonical(out)));
await worker.terminate();
