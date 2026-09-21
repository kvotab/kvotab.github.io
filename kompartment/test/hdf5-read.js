/**
 * Just enough of an HDF5 reader to check what the writer wrote.
 *
 * The suite has no libhdf5 and this tool has no dependencies, so the only way
 * to test a byte format is to read it back. This is not a general reader: it
 * understands exactly the subset ../src/io/hdf5.js produces -- version 2
 * object headers, compact groups, contiguous one-dimensional data, and
 * variable-length strings in a global heap -- and throws on anything else,
 * which is itself part of the test.
 *
 * Files written here have also been opened with the real library: `h5py`,
 * `h5ls` and `h5dump` read them, and the browser's h5wasm draws them. What
 * this guards is that they still do after an edit.
 */

import { lookup3 } from '../src/io/hdf5.js';

const SIGNATURE = [0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a];

/** Reads a file into `{ attrs, children }` / `{ attrs, values }`. */
export function readHDF5(bytes) {
	const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
	const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
	for (let i = 0; i < 8; i++) {
		if (u8[i] !== SIGNATURE[i]) throw new Error('not an HDF5 file');
	}
	if (u8[8] !== 2) throw new Error(`superblock version ${u8[8]}, expected 2`);
	if (u8[9] !== 8 || u8[10] !== 8) throw new Error('offsets and lengths must be 8 bytes');
	if (dv.getUint32(44, true) !== lookup3(u8, 0, 44)) throw new Error('superblock checksum');
	const eof = u64(dv, 28);
	if (eof !== u8.length) throw new Error(`end of file says ${eof}, file is ${u8.length}`);
	return object(u8, dv, u64(dv, 36));
}

/** Eight little-endian bytes as a number; all ones means "no address". */
function u64(dv, at) {
	let n = 0;
	for (let i = 7; i >= 0; i--) n = n * 256 + dv.getUint8(at + i);
	return n === 2 ** 64 ? -1 : n;
}

/** One object header, and everything it names. */
function object(u8, dv, addr) {
	if (String.fromCharCode(...u8.subarray(addr, addr + 4)) !== 'OHDR') {
		throw new Error(`no object header at ${addr}`);
	}
	if (u8[addr + 4] !== 2) throw new Error(`object header version ${u8[addr + 4]}`);
	const flags = u8[addr + 5];
	if (flags & 0x20 || flags & 0x10 || flags & 0x04) throw new Error(`header flags ${flags}`);
	let p = addr + 6;
	const size = [1, 2, 4, 8].map((n, i) => (i === (flags & 3) ? n : 0)).reduce((a, b) => a + b);
	let chunk = 0;
	for (let i = size - 1; i >= 0; i--) chunk = chunk * 256 + u8[p + i];
	p += size;
	const end = p + chunk;
	if (dv.getUint32(end, true) !== lookup3(u8, addr, end - addr)) {
		throw new Error(`object header checksum at ${addr}`);
	}

	const out = { attrs: {} };
	const links = [];
	let dims = null;
	let dt = null;
	let dataAddr = -1;
	let dataSize = 0;
	while (p < end - 3) {
		const type = u8[p];
		const length = dv.getUint16(p + 1, true);
		p += 4;
		const at = p;
		p += length;
		if (type === 0x06) { // link
			const nameLen = u8[at + 2];
			if (u8[at + 1] !== 0) throw new Error('only short ASCII link names are read here');
			links.push({
				name: new TextDecoder().decode(u8.subarray(at + 3, at + 3 + nameLen)),
				addr: u64(dv, at + 3 + nameLen),
			});
		} else if (type === 0x01) { // dataspace
			dims = dataspace(u8, dv, at);
		} else if (type === 0x03) { // datatype
			dt = datatype(u8, dv, at);
		} else if (type === 0x08) { // layout
			if (u8[at] !== 3 || u8[at + 1] !== 1) throw new Error('only contiguous layout is read here');
			dataAddr = u64(dv, at + 2);
			dataSize = u64(dv, at + 10);
		} else if (type === 0x0c) { // attribute
			const a = attribute(u8, dv, at);
			out.attrs[a.name] = a.value;
		}
	}

	if (dims) {
		out.values = values(u8, dv, dt, dims, dataAddr, dataSize);
		out.dims = dims;
		out.dtype = dt.name;
		return out;
	}
	out.children = new Map(links.map((l) => [l.name, object(u8, dv, l.addr)]));
	return out;
}

/** A version 2 dataspace: the dimensions, or `[]` for a scalar. */
function dataspace(u8, dv, at) {
	if (u8[at] !== 2) throw new Error(`dataspace version ${u8[at]}`);
	const n = u8[at + 1];
	const out = [];
	for (let i = 0; i < n; i++) out.push(u64(dv, at + 4 + i * 8));
	return out;
}

/** Which of the writer's three datatypes this is. */
function datatype(u8, dv, at) {
	const cls = u8[at] & 0x0f;
	const size = dv.getUint32(at + 4, true);
	if (cls === 1) return { name: size === 8 ? 'f64' : 'f32', size };
	if (cls === 0) return { name: 'i32', size };
	if (cls === 9) {
		if ((u8[at + 1] & 0x0f) !== 1) throw new Error('only variable-length strings are read here');
		return { name: 'str', size };
	}
	throw new Error(`datatype class ${cls}`);
}

/** The values behind a dataspace, whatever kind they are. */
function values(u8, dv, dt, dims, addr, size) {
	const n = dims.length ? dims.reduce((a, b) => a * b, 1) : 1;
	if (!n) return [];
	if (size !== n * dt.size) throw new Error(`layout says ${size} bytes, expected ${n * dt.size}`);
	const out = [];
	for (let i = 0; i < n; i++) {
		const p = addr + i * dt.size;
		if (dt.name === 'str') out.push(heapString(u8, dv, p));
		else if (dt.name === 'f64') out.push(dv.getFloat64(p, true));
		else if (dt.name === 'f32') out.push(dv.getFloat32(p, true));
		else out.push(dv.getInt32(p, true));
	}
	return out;
}

/** One 16-byte heap ID, followed into its collection. */
function heapString(u8, dv, at) {
	const length = dv.getUint32(at, true);
	const collection = u64(dv, at + 4);
	const index = dv.getUint32(at + 12, true);
	if (String.fromCharCode(...u8.subarray(collection, collection + 4)) !== 'GCOL') {
		throw new Error(`no global heap at ${collection}`);
	}
	let p = collection + 16;
	const end = collection + u64(dv, collection + 8);
	while (p < end) {
		const idx = dv.getUint16(p, true);
		const size = u64(dv, p + 8);
		if (idx === index) {
			if (size !== length) throw new Error(`heap object ${index} is ${size}, id says ${length}`);
			return new TextDecoder().decode(u8.subarray(p + 16, p + 16 + size));
		}
		if (idx === 0) break; // free space: the rest of the collection
		p += 16 + Math.ceil(size / 8) * 8;
	}
	throw new Error(`no heap object ${index}`);
}

/** A version 3 attribute message. */
function attribute(u8, dv, at) {
	if (u8[at] !== 3) throw new Error(`attribute version ${u8[at]}`);
	const nameSize = dv.getUint16(at + 2, true);
	const dtSize = dv.getUint16(at + 4, true);
	const dsSize = dv.getUint16(at + 6, true);
	let p = at + 9;
	const name = new TextDecoder().decode(u8.subarray(p, p + nameSize - 1));
	p += nameSize;
	const dt = datatype(u8, dv, p);
	p += dtSize;
	const dims = dataspace(u8, dv, p);
	p += dsSize;
	const read = values(u8, dv, dt, dims, p, (dims.length ? dims.reduce((a, b) => a * b, 1) : 1) * dt.size);
	return { name, value: dims.length ? read : read[0] };
}

/** Whatever is at `path`, or null. */
export function at(root, path) {
	let node = root;
	for (const part of path.split('/').filter(Boolean)) {
		node = node.children?.get(part);
		if (!node) return null;
	}
	return node;
}

/**
 * Every dataset path in the file, sorted.
 *
 * Appended one at a time rather than spread. `push(...list)` passes every
 * element as an argument, and `BMA1_FSAR_CC516.eas` writes 831,314 datasets --
 * past what a call can carry, so this threw `Maximum call stack size exceeded`
 * from inside the test helper on the one file big enough to need checking.
 * The same lesson as `expand` in ../src/sim/runner.js.
 */
export function paths(root, prefix = '') {
	if (!root.children) return [prefix];
	const out = [];
	for (const [name, child] of root.children) {
		for (const p of paths(child, `${prefix}/${name}`)) out.push(p);
	}
	return out.sort();
}
