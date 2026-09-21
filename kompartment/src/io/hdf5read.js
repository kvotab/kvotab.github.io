/**
 * Reading HDF5, by hand, in the page.
 *
 * The other half of ./hdf5.js, and it has more to do. That module writes one
 * dialect -- version 2 object headers with compact links, which needs no
 * B-tree -- and can write only what it chooses to. A reader has to take what
 * it is given, and what it is given is whatever wrote the file:
 *
 *   **h5py and libhdf5 write version 1.** A group is a *symbol table*: a
 *   message pointing at a version 1 B-tree of names and a local heap holding
 *   the names themselves. That is what the data files these read are, so the
 *   B-tree walk is not optional.
 *
 *   **This tool writes version 2.** A group's links are messages in its own
 *   object header. Reading its own output back is what makes a round trip
 *   testable without a second program.
 *
 * Both are here. What is deliberately *not* here is everything a data file
 * does not contain: chunked and compressed layouts, compound and enumerated
 * types, references, dimension scales, fractal-heap links, and anything with
 * more than three dimensions. Each of those is refused by name, so a file that
 * cannot be read says which feature it wanted rather than coming back empty.
 *
 * References: the HDF5 File Format Specification version 3.0 — II.A (the
 * superblock), III.A (symbol tables), IV.A (object headers, both versions) and
 * their messages, V.A (version 1 B-trees).
 */

import { inflateRaw } from './inflate.js';

export class HDF5ReadError extends Error {
	constructor(message) {
		super(message);
		this.name = 'HDF5ReadError';
	}
}

const SIGNATURE = [0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a];

const MSG = {
	NIL: 0x00,
	DATASPACE: 0x01,
	DATATYPE: 0x03,
	FILL_OLD: 0x04,
	FILL: 0x05,
	LINK: 0x06,
	LAYOUT: 0x08,
	ATTRIBUTE: 0x0c,
	FILTER: 0x0b,
	OBJECT_HEADER_CONTINUATION: 0x10,
	SYMBOL_TABLE: 0x11,
};

/** The filters a chunk may have been put through, by the id HDF5 gives them. */
const FILTER = { DEFLATE: 1, SHUFFLE: 2, FLETCHER32: 3 };

const UTF8 = new TextDecoder('utf-8');

/** A cursor over the file, with the offset and length sizes it was told. */
class Reader {
	constructor(bytes, offsetSize = 8, lengthSize = 8) {
		this.u8 = bytes;
		this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
		this.offsetSize = offsetSize;
		this.lengthSize = lengthSize;
	}

	u8At(p) { return this.view.getUint8(p); }

	u16(p) { return this.view.getUint16(p, true); }

	u32(p) { return this.view.getUint32(p, true); }

	/**
	 * An offset or a length, which are 2, 4 or 8 bytes depending on the file.
	 *
	 * Eight-byte values come back as a Number rather than a BigInt: a file
	 * larger than 2^53 bytes is not one a browser tab is going to hold, and
	 * every arithmetic site downstream would otherwise have to be BigInt too.
	 * `undefined` is the all-ones "not here" address, which is what an unset
	 * pointer looks like in this format.
	 */
	sized(p, size) {
		if (size === 2) { const v = this.u16(p); return v === 0xffff ? undefined : v; }
		if (size === 4) { const v = this.u32(p); return v === 0xffffffff ? undefined : v; }
		if (size === 8) {
			const lo = this.u32(p);
			const hi = this.u32(p + 4);
			if (lo === 0xffffffff && hi === 0xffffffff) return undefined;
			if (hi > 0x1fffff) throw new HDF5ReadError('This file addresses more than 8 EB.');
			return hi * 4294967296 + lo;
		}
		let v = 0;
		for (let i = size - 1; i >= 0; i--) v = v * 256 + this.u8At(p + i);
		return v;
	}

	offset(p) { return this.sized(p, this.offsetSize); }

	length(p) { return this.sized(p, this.lengthSize); }

	/** A NUL-terminated name, and where the next byte is. */
	name(p) {
		let end = p;
		while (end < this.u8.length && this.u8[end] !== 0) end++;
		return { text: UTF8.decode(this.u8.subarray(p, end)), next: end + 1 };
	}

	is(p, text) {
		for (let i = 0; i < text.length; i++) if (this.u8[p + i] !== text.charCodeAt(i)) return false;
		return true;
	}
}

/** Where the superblock is: byte 0, or a power-of-two offset after it. */
function findSuperblock(bytes) {
	for (let at = 0; at < bytes.length; at = at === 0 ? 512 : at * 2) {
		let ok = true;
		for (let i = 0; i < 8; i++) if (bytes[at + i] !== SIGNATURE[i]) { ok = false; break; }
		if (ok) return at;
		if (at > 0x100000) break;
	}
	throw new HDF5ReadError('This is not an HDF5 file — the signature is missing.');
}

/**
 * The superblock, and where the root object is.
 *
 * Versions 0 and 1 end in a *symbol table entry* for the root group, whose
 * second field is the object header's address. Versions 2 and 3 name that
 * address directly.
 */
function superblock(bytes) {
	const base = findSuperblock(bytes);
	const probe = new Reader(bytes);
	const version = probe.u8At(base + 8);
	if (version > 3) {
		throw new HDF5ReadError(`Superblock version ${version} is newer than this reader.`);
	}
	if (version <= 1) {
		const offsetSize = probe.u8At(base + 13);
		const lengthSize = probe.u8At(base + 14);
		const r = new Reader(bytes, offsetSize, lengthSize);
		// Base address, free-space, end-of-file, driver, then the root entry.
		let p = base + 24 + (version === 1 ? 4 : 0);
		p += offsetSize * 4;
		// A symbol table entry: link name offset, object header address, ...
		const root = r.offset(p + offsetSize);
		return { r, root };
	}
	const offsetSize = probe.u8At(base + 9);
	const lengthSize = probe.u8At(base + 10);
	const r = new Reader(bytes, offsetSize, lengthSize);
	const root = r.offset(base + 12 + offsetSize * 3);
	return { r, root };
}

/* ==========================================================================
 * OBJECT HEADERS
 * ======================================================================= */

/**
 * Every message of one object, both header versions, continuations followed.
 *
 * @returns {Array<{type: number, at: number, size: number}>}
 */
function messagesOf(r, address, seen = new Set()) {
	if (address == null || seen.has(address)) return [];
	seen.add(address);
	return r.is(address, 'OHDR')
		? messagesV2(r, address, seen)
		: messagesV1(r, address, seen);
}

/**
 * Version 1: a chunk of messages, and every continuation it points at.
 *
 * Driven by the chunk's *bounds* rather than by the message count, and a
 * continuation does **not** end the chunk it sits in. An object with two of
 * them -- which is what a dataset written one attribute at a time looks like,
 * since each attribute that does not fit starts another block -- has messages
 * between the two and after the second. Stopping at the first cost this file
 * four hundred of its nine hundred datasets: one whose datatype or layout is
 * in the part that was skipped is not reported as broken, it simply is not
 * there.
 */
function messagesV1(r, address, seen) {
	const version = r.u8At(address);
	if (version !== 1) {
		throw new HDF5ReadError(`Object header version ${version} is not one this reads.`);
	}
	const out = [];
	const queue = [{ at: address + 16, end: address + 16 + r.u32(address + 8) }];
	while (queue.length) {
		const chunk = queue.shift();
		let p = chunk.at;
		while (p + 8 <= chunk.end) {
			const type = r.u16(p);
			const size = r.u16(p + 2);
			const at = p + 8;
			p = at + size;
			if (p > chunk.end) break;
			// A NIL message is the space a deleted one left behind.
			if (type === MSG.NIL) continue;
			if (type === MSG.OBJECT_HEADER_CONTINUATION) {
				const to = r.offset(at);
				const len = r.length(at + r.offsetSize);
				if (to != null && len && !seen.has(to)) {
					seen.add(to);
					queue.push({ at: to, end: to + len });
				}
				continue;
			}
			out.push({ type, at, size });
		}
	}
	return out;
}

function messagesV2(r, address, seen) {
	const version = r.u8At(address + 4);
	if (version !== 2) {
		throw new HDF5ReadError(`Object header version ${version} is not one this reads.`);
	}
	const flags = r.u8At(address + 5);
	let p = address + 6;
	if (flags & 0x20) p += 16;        // access, modification, change, birth times
	if (flags & 0x10) p += 4;         // maximum compact and minimum dense
	const sizeBytes = [1, 2, 4, 8][flags & 3];
	const chunkSize = r.sized(p, sizeBytes);
	p += sizeBytes;
	const out = [];
	// The gap at the end is the checksum, which is not read: a file whose
	// checksum is wrong is a file this cannot help with either way.
	const end = p + chunkSize - 4;
	const tracked = !!(flags & 4);
	while (p + 4 <= end) {
		const type = r.u8At(p);
		const len = r.u16(p + 1);
		let at = p + 4;
		if (tracked) at += 2;
		p = at + len;
		if (type === MSG.OBJECT_HEADER_CONTINUATION) {
			const to = r.offset(at);
			const howBig = r.length(at + r.offsetSize);
			out.push(...continuedV2(r, to, howBig, seen, tracked));
			continue;
		}
		out.push({ type, at, size: len });
	}
	return out;
}

function continuedV2(r, address, size, seen, tracked) {
	if (address == null || seen.has(address)) return [];
	seen.add(address);
	if (!r.is(address, 'OCHK')) return [];
	const out = [];
	let p = address + 4;
	const end = address + (size ?? 0) - 4;
	while (p + 4 <= end) {
		const type = r.u8At(p);
		const len = r.u16(p + 1);
		let at = p + 4;
		if (tracked) at += 2;
		p = at + len;
		if (type === MSG.OBJECT_HEADER_CONTINUATION) {
			out.push(...continuedV2(r, r.offset(at), r.length(at + r.offsetSize), seen, tracked));
			continue;
		}
		out.push({ type, at, size: len });
	}
	return out;
}

/* ==========================================================================
 * LINKS: both ways a group holds its children
 * ======================================================================= */

/** A version 2 LINK message: `{name, address}`. */
function linkMessage(r, at) {
	const version = r.u8At(at);
	if (version !== 1) return null;
	const flags = r.u8At(at + 1);
	let p = at + 2;
	if (flags & 0x08) p += 1;                 // link type, when not hard
	if (flags & 0x04) p += 8;                 // creation order
	if (flags & 0x10) p += 1;                 // character set
	const lenBytes = [1, 2, 4, 8][flags & 3];
	const len = r.sized(p, lenBytes);
	p += lenBytes;
	const name = UTF8.decode(r.u8.subarray(p, p + len));
	p += len;
	// Only a hard link has an address; a soft or external one names a path
	// this reader has nothing to do with.
	if (flags & 0x08 && r.u8At(at + 2) !== 0) return { name, address: null };
	return { name, address: r.offset(p) };
}

/** A local heap: the strings a symbol table's names are offsets into. */
function localHeap(r, address) {
	if (address == null || !r.is(address, 'HEAP')) return null;
	const data = r.offset(address + 8 + r.lengthSize * 2);
	return (offset) => (data == null ? '' : r.name(data + offset).text);
}

/**
 * Every child of a version 1 group, by walking its B-tree.
 *
 * The tree's leaves point at symbol table nodes, each a run of entries; an
 * internal node points at more trees. Both carry their children's addresses
 * after the keys, which is why the key size has to be counted even though no
 * key is read: the names come from the heap, not from the tree.
 */
function symbolTable(r, treeAt, heapAt, out = []) {
	const nameOf = localHeap(r, heapAt);
	if (!nameOf) return out;
	walkTree(r, treeAt, nameOf, out, new Set());
	return out;
}

function walkTree(r, address, nameOf, out, seen) {
	if (address == null || seen.has(address) || !r.is(address, 'TREE')) return;
	seen.add(address);
	const type = r.u8At(address + 4);
	const level = r.u8At(address + 5);
	const used = r.u16(address + 6);
	// Keys and children alternate: K+1 keys around K children. A group node's
	// key is one length-sized offset into the heap.
	let p = address + 8 + r.offsetSize * 2;
	for (let i = 0; i < used; i++) {
		p += r.lengthSize;                       // the key before this child
		const child = r.offset(p);
		p += r.offsetSize;
		if (type !== 0) continue;                // a chunk tree, not a group's
		if (level > 0) walkTree(r, child, nameOf, out, seen);
		else readSNOD(r, child, nameOf, out);
	}
}

function readSNOD(r, address, nameOf, out) {
	if (address == null || !r.is(address, 'SNOD')) return;
	const used = r.u16(address + 6);
	const entry = r.offsetSize * 2 + 4 + 4 + 16;
	for (let i = 0; i < used; i++) {
		const at = address + 8 + i * entry;
		const name = nameOf(r.offset(at));
		const header = r.offset(at + r.offsetSize);
		const kind = r.u32(at + r.offsetSize * 2);
		// Cache type 2 is a symbolic link, which points at a path rather than
		// an object; there is nothing under it to read.
		if (kind === 2) continue;
		out.push({ name, address: header });
	}
}

/* ==========================================================================
 * DATATYPE, DATASPACE, LAYOUT
 * ======================================================================= */

function datatype(r, at) {
	const b0 = r.u8At(at);
	const cls = b0 & 0x0f;
	const flags = r.u8At(at + 1) | (r.u8At(at + 2) << 8) | (r.u8At(at + 3) << 16);
	const size = r.u32(at + 4);
	if (cls === 0) return { cls: 'int', size, signed: !!(flags & 0x08), little: !(flags & 1) };
	if (cls === 1) return { cls: 'float', size, little: !(flags & 1) };
	if (cls === 3) return { cls: 'string', size, padding: flags & 0x0f };
	if (cls === 9) {
		// A variable-length *string* is type 1 in the low nibble of the flags;
		// anything else is a variable-length sequence of something, which no
		// data file this reads uses.
		if ((flags & 0x0f) !== 1) return { cls: 'unsupported', what: 'a variable-length sequence' };
		return { cls: 'vlenstr', size };
	}
	if (cls === 8) {
		// An enumeration is a base type with names hung off it, and a Python
		// `True` written by h5py is one: an 8-bit integer called TRUE. The
		// names are not data, so what comes back is the number underneath --
		// which is what every reader of `lookup_table` wants anyway.
		const base = datatype(r, at + 8);
		return base.cls === 'unsupported' ? base : { ...base, size: base.size || size };
	}
	const names = {
		2: 'a time', 4: 'a bitfield', 5: 'an opaque type', 6: 'a compound type',
		7: 'a reference', 10: 'an array',
	};
	return { cls: 'unsupported', what: names[cls] ?? `datatype class ${cls}` };
}

function dataspace(r, at) {
	const version = r.u8At(at);
	const rank = r.u8At(at + 1);
	const flags = r.u8At(at + 2);
	// Version 2 says the kind in byte 3, and the numbering is not the obvious
	// one: 0 is *scalar* -- one element, no dimensions -- 1 is simple, and 2
	// is the null dataspace that really does hold nothing. Reading 0 as null
	// silently emptied every scalar attribute written that way, which is what
	// a unit and a lookup table's times are.
	if (version === 2 && r.u8At(at + 3) === 2) return { dims: [], count: 0 };
	let p = at + (version === 1 ? 8 : 4);
	const dims = [];
	for (let i = 0; i < rank; i++) { dims.push(r.length(p)); p += r.lengthSize; }
	void flags;
	const count = dims.reduce((a, b) => a * b, 1);
	return { dims, count: rank === 0 ? 1 : count };
}

/** Where the data is: `{kind, address, size}` or a refusal. */
function layout(r, at) {
	const version = r.u8At(at);
	if (version === 1 || version === 2) {
		const rank = r.u8At(at + 1);
		const cls = r.u8At(at + 2);
		if (cls === 0) return { kind: 'compact', address: at + 8 + (rank * 4) + 4, size: null };
		if (cls === 1) return { kind: 'contiguous', address: r.offset(at + 8), size: null };
		// Version 1 puts the address first and the sizes after, and counts the
		// element size among them exactly as version 3 does.
		const address = r.offset(at + 8);
		const dims = [];
		for (let i = 0; i < rank; i++) dims.push(r.u32(at + 8 + r.offsetSize + i * 4));
		return { kind: 'chunked', address, ndims: rank, chunk: dims.slice(0, -1), elem: dims[rank - 1] };
	}
	if (version === 3 || version === 4) {
		const cls = r.u8At(at + 1);
		if (cls === 0) {
			const size = r.u16(at + 2);
			return { kind: 'compact', address: at + 4, size };
		}
		if (cls === 1) {
			return {
				kind: 'contiguous',
				address: r.offset(at + 2),
				size: r.length(at + 2 + r.offsetSize),
			};
		}
		if (cls === 2) {
			// `ndims` counts one more than the dataset's rank: the last entry
			// of the size list is the element size, not a dimension. The data
			// lives in a version 1 B-tree of chunks at `address`.
			const ndims = r.u8At(at + 2);
			const address = r.offset(at + 3);
			const dims = [];
			for (let i = 0; i < ndims; i++) dims.push(r.u32(at + 3 + r.offsetSize + i * 4));
			return { kind: 'chunked', address, ndims, chunk: dims.slice(0, -1), elem: dims[ndims - 1] };
		}
		return { kind: 'unsupported', what: 'a virtual layout' };
	}
	return { kind: 'unsupported', what: `layout version ${version}` };
}

/* ==========================================================================
 * CHUNKS
 *
 * A chunked dataset is not one run of bytes: it is a version 1 B-tree whose
 * leaves name the chunks, each of which may have been squeezed through a
 * filter pipeline on the way out. It is the layout h5py chooses the moment
 * anything is compressed, which for a file of a thousand realisations is
 * always -- so a reader without this opens none of them.
 * ======================================================================= */

/**
 * The filters a dataset's chunks were put through, in the order they were
 * applied. Undoing them means walking this backwards.
 */
function filterPipeline(r, at) {
	const version = r.u8At(at);
	const count = r.u8At(at + 1);
	let p = at + (version === 1 ? 8 : 2);
	const out = [];
	for (let i = 0; i < count && p < r.u8.length; i++) {
		const id = r.u16(p);
		// Version 2 writes the name length only for a filter it does not know
		// by number; version 1 always writes it.
		const named = version === 1 || id >= 256;
		const nameLen = named ? r.u16(p + 2) : 0;
		const values = r.u16(p + 6);
		p += 8 + (version === 1 ? Math.ceil(nameLen / 8) * 8 : nameLen);
		const client = [];
		for (let k = 0; k < values; k++) client.push(r.u32(p + k * 4));
		p += version === 1 ? Math.ceil(values / 2) * 8 : values * 4;
		out.push({ id, client });
	}
	return out;
}

/** A chunk's bytes, with whatever was done to them undone. */
function unfilter(bytes, filters, mask) {
	let out = bytes;
	for (let i = filters.length - 1; i >= 0; i--) {
		// A chunk may skip a filter -- the pipeline is per dataset and the
		// mask is per chunk, which is how HDF5 stores an incompressible one.
		if (mask & (1 << i)) continue;
		const f = filters[i];
		if (f.id === FILTER.DEFLATE) {
			// The gzip filter writes a zlib stream: two header bytes, the
			// deflate data, then an Adler-32 this does not check.
			out = inflateRaw(out.subarray(2));
		} else if (f.id === FILTER.SHUFFLE) {
			out = unshuffle(out, f.client[0] || 1);
		} else if (f.id === FILTER.FLETCHER32) {
			// A checksum of the four bytes at the end, and nothing else.
			out = out.subarray(0, out.length - 4);
		} else {
			throw new HDF5ReadError(`filter ${f.id} is one this reader does not undo`);
		}
	}
	return out;
}

/**
 * Shuffle, undone.
 *
 * The filter writes every element's first byte, then every element's second,
 * and so on -- which puts like next to like and lets the compressor do better.
 * Putting them back is the same walk the other way round.
 */
function unshuffle(bytes, size) {
	if (size <= 1) return bytes;
	const n = Math.floor(bytes.length / size);
	const out = new Uint8Array(bytes.length);
	let at = 0;
	for (let b = 0; b < size; b++) {
		for (let i = 0; i < n; i++) out[i * size + b] = bytes[at++];
	}
	// A tail that is not a whole element is copied as it lies.
	for (let i = n * size; i < bytes.length; i++) out[i] = bytes[i];
	return out;
}

/**
 * Every chunk of a dataset, assembled into one run of bytes.
 *
 * The B-tree's keys carry each chunk's *offset* in the dataset, so a chunk is
 * placed rather than appended -- and a dataset whose chunk covers the whole of
 * it, which is what these files hold, is one copy.
 */
function readChunks(r, where, filters, dims, elem) {
	const total = dims.reduce((a, b) => a * b, 1) * elem;
	if (!Number.isFinite(total) || total <= 0) return new Uint8Array(0);
	if (total > 1 << 30) {
		throw new HDF5ReadError(`${(total / 1e6).toFixed(0)} MB is more than this reads at once`);
	}
	const out = new Uint8Array(total);
	const seen = new Set();
	const keySize = 4 + 4 + 8 * where.ndims;
	walkChunkTree(r, where.address, keySize, seen, (key, address) => {
		const size = r.u32(key);
		const mask = r.u32(key + 4);
		const offset = [];
		for (let i = 0; i < where.ndims - 1; i++) offset.push(r.sized(key + 8 + i * 8, 8));
		let bytes;
		try {
			bytes = unfilter(r.u8.subarray(address, address + size), filters, mask);
		} catch (e) {
			throw new HDF5ReadError(`a chunk could not be read — ${e.message}`);
		}
		place(out, bytes, dims, where.chunk, offset, elem);
	});
	return out;
}

function walkChunkTree(r, address, keySize, seen, onChunk) {
	if (address == null || seen.has(address) || !r.is(address, 'TREE')) return;
	seen.add(address);
	if (r.u8At(address + 4) !== 1) return;
	const level = r.u8At(address + 5);
	const used = r.u16(address + 6);
	let p = address + 8 + r.offsetSize * 2;
	for (let i = 0; i < used; i++) {
		const key = p;
		p += keySize;
		const child = r.offset(p);
		p += r.offsetSize;
		if (level > 0) walkChunkTree(r, child, keySize, seen, onChunk);
		else if (child != null) onChunk(key, child);
	}
}

/** One chunk's bytes into the dataset, at the offset its key gave. */
function place(out, bytes, dims, chunk, offset, elem) {
	if (dims.length <= 1) {
		const start = (offset[0] ?? 0) * elem;
		const room = Math.min(bytes.length, out.length - start);
		if (room > 0) out.set(bytes.subarray(0, room), start);
		return;
	}
	// Two dimensions, which is a matrix of realisations: rows of the chunk go
	// into rows of the dataset, and a chunk narrower than the dataset leaves
	// the rest of each row alone.
	const [rows, cols] = dims;
	const [cr, cc] = chunk;
	const [r0, c0] = [offset[0] ?? 0, offset[1] ?? 0];
	for (let i = 0; i < cr && r0 + i < rows; i++) {
		const width = Math.min(cc, cols - c0) * elem;
		const from = i * cc * elem;
		const to = ((r0 + i) * cols + c0) * elem;
		if (from + width <= bytes.length && to + width <= out.length) {
			out.set(bytes.subarray(from, from + width), to);
		}
	}
}

/** The elements themselves, as numbers or as strings. */
function readValues(r, type, space, where) {
	const n = space.count;
	if (!n || where.address == null) return [];
	const p = where.address;
	// Numbers come back in a typed array rather than a plain one. A file of a
	// thousand realisations over four hundred times is 394,000 values in one
	// dataset and fifty-three such datasets; as boxed JS numbers that is a
	// couple of hundred megabytes of a browser tab, and as `Float64Array` it
	// is the bytes and nothing else.
	if (type.cls === 'float') {
		const out = new Float64Array(n);
		for (let i = 0; i < n; i++) {
			out[i] = type.size === 4
				? r.view.getFloat32(p + i * 4, type.little)
				: r.view.getFloat64(p + i * 8, type.little);
		}
		return out;
	}
	if (type.cls === 'int') {
		const out = new Float64Array(n);
		for (let i = 0; i < n; i++) {
			const q = p + i * type.size;
			if (type.size === 1) out[i] = type.signed ? r.view.getInt8(q) : r.view.getUint8(q);
			else if (type.size === 2) out[i] = type.signed ? r.view.getInt16(q, type.little) : r.u16(q);
			else if (type.size === 4) out[i] = type.signed ? r.view.getInt32(q, type.little) : r.u32(q);
			else out[i] = Number(r.sized(q, type.size) ?? 0);
		}
		return out;
	}
	if (type.cls === 'string') {
		const out = new Array(n);
		for (let i = 0; i < n; i++) {
			const raw = r.u8.subarray(p + i * type.size, p + (i + 1) * type.size);
			let end = raw.length;
			while (end > 0 && raw[end - 1] === 0) end--;
			out[i] = UTF8.decode(raw.subarray(0, end));
		}
		return out;
	}
	if (type.cls === 'vlenstr') {
		const out = new Array(n);
		for (let i = 0; i < n; i++) out[i] = globalHeapString(r, p + i * type.size);
		return out;
	}
	return [];
}

/**
 * A variable-length string, which is a pointer into a global heap collection.
 *
 * The id is a length, then the collection's address, then the object's index
 * inside it. The collection is a run of objects each carrying its own size.
 */
function globalHeapString(r, at) {
	const length = r.u32(at);
	const collection = r.offset(at + 4);
	const index = r.u32(at + 4 + r.offsetSize);
	if (collection == null || !r.is(collection, 'GCOL')) return '';
	let p = collection + 8 + r.lengthSize;
	const end = collection + (r.length(collection + 8) ?? 0);
	while (p + 8 <= end) {
		const id = r.u16(p);
		const size = r.length(p + 8);
		const body = p + 8 + r.lengthSize;
		if (id === 0) break;
		if (id === index) {
			const take = Math.min(length, size ?? length);
			return UTF8.decode(r.u8.subarray(body, body + take));
		}
		// Objects are padded to a multiple of eight.
		p = body + Math.ceil((size ?? 0) / 8) * 8;
	}
	return '';
}

/** One attribute message, whichever version wrote it. */
function attribute(r, at) {
	const version = r.u8At(at);
	let p;
	let nameLen;
	let typeLen;
	let spaceLen;
	if (version === 1) {
		nameLen = r.u16(at + 2);
		typeLen = r.u16(at + 4);
		spaceLen = r.u16(at + 6);
		p = at + 8;
		const name = r.name(p).text;
		p += Math.ceil(nameLen / 8) * 8;
		const type = datatype(r, p);
		p += Math.ceil(typeLen / 8) * 8;
		const space = dataspace(r, p);
		p += Math.ceil(spaceLen / 8) * 8;
		return { name, value: readValues(r, type, space, { address: p }), type, space };
	}
	if (version !== 2 && version !== 3) return null;
	const flags = r.u8At(at + 1);
	nameLen = r.u16(at + 2);
	typeLen = r.u16(at + 4);
	spaceLen = r.u16(at + 6);
	p = at + 8 + (version === 3 ? 1 : 0);
	const name = UTF8.decode(r.u8.subarray(p, p + nameLen - 1));
	p += nameLen;
	// A shared datatype or dataspace points elsewhere; a data file does not
	// use them, and reading one as if it were inline would be nonsense.
	if (flags & 3) return { name, value: [], shared: true };
	const type = datatype(r, p);
	p += typeLen;
	const space = dataspace(r, p);
	p += spaceLen;
	return { name, value: readValues(r, type, space, { address: p }), type, space };
}

/* ==========================================================================
 * THE WALK
 * ======================================================================= */

/**
 * Every dataset in the file, by path.
 *
 * @param {ArrayBuffer|Uint8Array} bytes
 * @returns {Promise<{datasets: Array<{path, values, dims, attrs}>, problems: string[]}>}
 */
export async function readHDF5(bytes) {
	const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
	const { r, root } = superblock(u8);
	const datasets = [];
	const problems = [];
	const seen = new Set();
	walk(r, root, '', datasets, problems, seen, 0);
	return { datasets, problems };
}

function walk(r, address, path, datasets, problems, seen, depth) {
	if (address == null) return;
	// A cycle is possible through a hard link that points back up, and a
	// hundred levels is far past any real tree.
	if (seen.has(address) || depth > 100) return;
	seen.add(address);

	let messages;
	try {
		messages = messagesOf(r, address);
	} catch (e) {
		problems.push(`${path || '/'}: ${e.message}`);
		return;
	}

	const attrs = {};
	for (const m of messages) {
		if (m.type !== MSG.ATTRIBUTE) continue;
		try {
			const a = attribute(r, m.at);
			if (!a || !a.name) continue;
			// One value rather than a list of one: `unit` is a string, not a
			// string in a box, and every reader downstream would unbox it.
			attrs[a.name] = a.value.length === 1 ? a.value[0] : a.value;
		} catch (e) {
			problems.push(`${path || '/'}: an attribute could not be read — ${e.message}`);
		}
	}

	const children = [];
	for (const m of messages) {
		if (m.type === MSG.LINK) {
			const link = linkMessage(r, m.at);
			if (link?.address != null) children.push(link);
		} else if (m.type === MSG.SYMBOL_TABLE) {
			const tree = r.offset(m.at);
			const heap = r.offset(m.at + r.offsetSize);
			symbolTable(r, tree, heap, children);
		}
	}

	if (children.length) {
		for (const c of children) {
			walk(r, c.address, `${path}/${c.name}`, datasets, problems, seen, depth + 1);
		}
		return;
	}

	// No links: a dataset, or an empty group. A dataset is the one with a
	// layout, which is what says where its elements are.
	const layoutMsg = messages.find((m) => m.type === MSG.LAYOUT);
	if (!layoutMsg) return;
	const typeMsg = messages.find((m) => m.type === MSG.DATATYPE);
	const spaceMsg = messages.find((m) => m.type === MSG.DATASPACE);
	if (!typeMsg || !spaceMsg) return;

	const type = datatype(r, typeMsg.at);
	if (type.cls === 'unsupported') {
		problems.push(`${path}: holds ${type.what}, which this reader does not open.`);
		return;
	}
	const where = layout(r, layoutMsg.at);
	if (where.kind === 'unsupported') {
		problems.push(`${path}: is stored with ${where.what}, which this reader does not open.`);
		return;
	}
	const space = dataspace(r, spaceMsg.at);
	// Two dimensions is a matrix of realisations: a release rate over 394
	// times for each of a thousand runs is `(394, 1000)`, and it is the shape
	// raw sample data arrives in. It comes back flat, with `dims` saying how
	// to read it -- HDF5 stores it in exactly this order, last dimension
	// varying fastest, so `values[t * n + i]` is realisation `i` at time `t`.
	if (space.dims.length > 2) {
		problems.push(`${path}: is ${space.dims.join('×')}, and this reads one or two `
			+ 'dimensions.');
		return;
	}
	try {
		let read = where;
		if (where.kind === 'chunked') {
			// The chunks, assembled and unfiltered, read as if they had been
			// one run of bytes all along.
			const pipe = messages.find((m) => m.type === MSG.FILTER);
			const bytes = readChunks(r, where,
				pipe ? filterPipeline(r, pipe.at) : [], space.dims, where.elem || type.size);
			read = { kind: 'contiguous', address: 0, size: bytes.length, over: new Reader(bytes) };
		}
		datasets.push({
			path,
			values: readValues(read.over ?? r, type, space, read),
			dims: space.dims,
			attrs,
		});
	} catch (e) {
		problems.push(`${path}: ${e.message}`);
	}
}
