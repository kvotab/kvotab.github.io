// V8's Math.pow at every call, for the Python port's tests (test_engine_julia.py).
//
//   node v8_pow.mjs
//
// One question a line on stdin, one answer a line on stdout: x and y as the 16 hex
// digits of their IEEE bytes, little-endian, the answer likewise. A run of the port
// asks as it goes and so takes V8's pow at every step in one pass, where the bridge's
// `pow` task answers only the arguments a run has already met.

import readline from 'node:readline';

const view = new DataView(new ArrayBuffer(8));

function fromHex(h) {
	for (let i = 0; i < 8; i++) view.setUint8(i, parseInt(h.substr(2 * i, 2), 16));
	return view.getFloat64(0, true);
}

function toHex(v) {
	view.setFloat64(0, v, true);
	let s = '';
	for (let i = 0; i < 8; i++) s += view.getUint8(i).toString(16).padStart(2, '0');
	return s;
}

readline.createInterface({ input: process.stdin }).on('line', (line) => {
	const [x, y] = line.split(' ');
	process.stdout.write(`${toHex(Math.pow(fromHex(x), fromHex(y)))}\n`);
});
