/**
 * Raw DEFLATE decompression (RFC 1951).
 *
 * The ZIP reader prefers the platform's own DecompressionStream, but
 * 'deflate-raw' is a recent addition: Node gained it after 20.10, and older
 * Safari lacks it. Rather than make the importer depend on a browser version,
 * this is the fallback -- and it keeps the project dependency-free.
 */

const LENGTH_BASE = [
	3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
	35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258,
];
const LENGTH_EXTRA = [
	0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
	3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];
const DIST_BASE = [
	1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
	257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
	8193, 12289, 16385, 24577,
];
const DIST_EXTRA = [
	0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
	7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13,
];
const CLEN_ORDER = [
	16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15,
];

/**
 * The most one entry may expand to.
 *
 * Nothing bounded the output before: `ensure` doubled until it ran out of
 * memory, and the native `DecompressionStream` path was unbounded too. DEFLATE
 * reaches about 1000:1 on repetitive text, so a one-megabyte entry in a file
 * somebody was sent expands to a gigabyte, and the import runs on the main
 * thread -- the tab freezes and then dies. The largest `model.xml` in the 211
 * real archives here is a few megabytes, so 256 MB is two orders of magnitude
 * of headroom and still refuses the attack.
 */
export const MAX_INFLATED = 256 * 1024 * 1024;

export class InflateError extends Error {
	constructor(message) {
		super(message);
		this.name = 'InflateError';
	}
}

/** A canonical Huffman decoder built from code lengths. */
function buildHuffman(lengths) {
	let maxBits = 0;
	for (const l of lengths) if (l > maxBits) maxBits = l;
	if (maxBits === 0) return { maxBits: 0, counts: new Int32Array(1), symbols: new Int32Array(0) };

	const counts = new Int32Array(maxBits + 1);
	for (const l of lengths) if (l) counts[l]++;

	const offsets = new Int32Array(maxBits + 2);
	for (let b = 1; b <= maxBits; b++) offsets[b + 1] = offsets[b] + counts[b];

	const symbols = new Int32Array(offsets[maxBits + 1]);
	for (let sym = 0; sym < lengths.length; sym++) {
		if (lengths[sym]) symbols[offsets[lengths[sym]]++] = sym;
	}
	return { maxBits, counts, symbols };
}

class BitReader {
	constructor(bytes) {
		this.bytes = bytes;
		this.pos = 0;
		this.bit = 0;
		this.buf = 0;
	}

	/** Reads `n` bits, least-significant first. */
	bits(n) {
		while (this.bit < n) {
			if (this.pos >= this.bytes.length) {
				throw new InflateError('Compressed data ended unexpectedly');
			}
			this.buf |= this.bytes[this.pos++] << this.bit;
			this.bit += 8;
		}
		const v = this.buf & ((1 << n) - 1);
		this.buf >>>= n;
		this.bit -= n;
		return v;
	}

	/** Decodes one symbol, walking the canonical code bit by bit. */
	symbol(table) {
		let code = 0;
		let first = 0;
		let index = 0;
		for (let len = 1; len <= table.maxBits; len++) {
			code |= this.bits(1);
			const count = table.counts[len];
			if (code - first < count) return table.symbols[index + (code - first)];
			index += count;
			first = (first + count) << 1;
			code <<= 1;
		}
		throw new InflateError('Invalid Huffman code');
	}

	alignToByte() {
		this.buf = 0;
		this.bit = 0;
	}
}

let FIXED_LIT = null;
let FIXED_DIST = null;

function fixedTables() {
	if (FIXED_LIT) return { lit: FIXED_LIT, dist: FIXED_DIST };
	const lengths = new Uint8Array(288);
	for (let i = 0; i < 144; i++) lengths[i] = 8;
	for (let i = 144; i < 256; i++) lengths[i] = 9;
	for (let i = 256; i < 280; i++) lengths[i] = 7;
	for (let i = 280; i < 288; i++) lengths[i] = 8;
	FIXED_LIT = buildHuffman(lengths);
	FIXED_DIST = buildHuffman(new Uint8Array(30).fill(5));
	return { lit: FIXED_LIT, dist: FIXED_DIST };
}

/**
 * @param {Uint8Array} data raw deflate stream
 * @param {number} [expectedSize] pre-sizes the output buffer when known
 * @returns {Uint8Array}
 */
export function inflateRaw(data, expectedSize = 0, limit = MAX_INFLATED) {
	const r = new BitReader(data);
	// Pre-sized from what the archive claims, but never beyond the cap: the
	// declared size is a number in the file, and a five-byte entry can claim
	// four gigabytes.
	const claimed = expectedSize > 0 ? Math.min(expectedSize, limit) : 0;
	let out = new Uint8Array(claimed || Math.max(1024, Math.min(limit, data.length * 4)));
	let len = 0;

	const ensure = (extra) => {
		if (len + extra <= out.length) return;
		if (len + extra > limit) {
			throw new InflateError(
				`the entry expands to more than ${Math.round(limit / 1048576)} MB, `
				+ `which is far larger than any real model -- the archive is either `
				+ `damaged or built to exhaust memory`,
			);
		}
		let size = Math.min(limit, out.length * 2);
		while (size < len + extra) size = Math.min(limit, size * 2);
		const grown = new Uint8Array(size);
		grown.set(out.subarray(0, len));
		out = grown;
	};

	for (;;) {
		const last = r.bits(1);
		const type = r.bits(2);

		if (type === 0) {
			// Stored: byte-aligned, with a length and its complement.
			r.alignToByte();
			if (r.pos + 4 > data.length) {
				throw new InflateError('Truncated stored block');
			}
			const n = data[r.pos] | (data[r.pos + 1] << 8);
			const nn = data[r.pos + 2] | (data[r.pos + 3] << 8);
			if ((n ^ 0xffff) !== nn) {
				throw new InflateError('Stored block length check failed');
			}
			r.pos += 4;
			if (r.pos + n > data.length) {
				throw new InflateError('Truncated stored block');
			}
			ensure(n);
			out.set(data.subarray(r.pos, r.pos + n), len);
			len += n;
			r.pos += n;
		} else if (type === 1 || type === 2) {
			let lit;
			let dist;
			if (type === 1) {
				({ lit, dist } = fixedTables());
			} else {
				const hlit = r.bits(5) + 257;
				const hdist = r.bits(5) + 1;
				const hclen = r.bits(4) + 4;

				const clen = new Uint8Array(19);
				for (let i = 0; i < hclen; i++) clen[CLEN_ORDER[i]] = r.bits(3);
				const clenTable = buildHuffman(clen);

				const lengths = new Uint8Array(hlit + hdist);
				let i = 0;
				while (i < lengths.length) {
					const sym = r.symbol(clenTable);
					if (sym < 16) {
						lengths[i++] = sym;
					} else if (sym === 16) {
						if (i === 0) throw new InflateError('Nothing to repeat');
						const prev = lengths[i - 1];
						let n = 3 + r.bits(2);
						while (n-- && i < lengths.length) lengths[i++] = prev;
					} else if (sym === 17) {
						let n = 3 + r.bits(3);
						while (n-- && i < lengths.length) lengths[i++] = 0;
					} else {
						let n = 11 + r.bits(7);
						while (n-- && i < lengths.length) lengths[i++] = 0;
					}
				}
				lit = buildHuffman(lengths.subarray(0, hlit));
				dist = buildHuffman(lengths.subarray(hlit));
			}

			for (;;) {
				const sym = r.symbol(lit);
				if (sym < 256) {
					ensure(1);
					out[len++] = sym;
				} else if (sym === 256) {
					break;
				} else {
					const li = sym - 257;
					if (li >= LENGTH_BASE.length) {
						throw new InflateError(`Invalid length symbol ${sym}`);
					}
					const length = LENGTH_BASE[li] + r.bits(LENGTH_EXTRA[li]);
					const ds = r.symbol(dist);
					if (ds >= DIST_BASE.length) {
						throw new InflateError(`Invalid distance symbol ${ds}`);
					}
					const distance = DIST_BASE[ds] + r.bits(DIST_EXTRA[ds]);
					if (distance > len) {
						throw new InflateError('Back-reference points before the output');
					}
					ensure(length);
					let from = len - distance;
					for (let k = 0; k < length; k++) out[len++] = out[from++];
				}
			}
		} else {
			throw new InflateError('Invalid block type');
		}

		if (last) break;
	}

	return out.subarray(0, len);
}
