/**
 * A small ZIP reader.
 *
 * An .eco project file is a ZIP of the project directory. To read one in a
 * browser without pulling in a dependency we parse the central directory ourselves and
 * hand the compressed bytes to the platform's own inflate via
 * DecompressionStream('deflate-raw'), which both modern browsers and Node 18+
 * provide.
 *
 * Supported: stored (method 0) and deflate (method 8), the only two that
 * appear in these files. Encrypted archives are detected and refused with an
 * explanation rather than a corrupt result.
 */

import { inflateRaw as inflateRawJS, InflateError, MAX_INFLATED } from './inflate.js';

export class ZipError extends Error {
	constructor(message) {
		super(message);
		this.name = 'ZipError';
	}
}

/**
 * The most a whole archive may expand to.
 *
 * MAX_INFLATED bounds one entry, and one entry was never the danger: a 26 MB
 * archive of a hundred entries, each just inside the per-entry cap, expands to
 * 25 GB -- and the reader held every one of them at once. The budget below is
 * shared across the archive, so the hundredth entry is refused by what the
 * ninety-nine before it already spent. The same number as the per-entry cap,
 * because how much may come out of a file does not depend on how many pieces
 * it arrives in.
 */
export const MAX_ARCHIVE_INFLATED = MAX_INFLATED;

/** What is left of one archive's decompression allowance. */
class Budget {
	constructor(limit) {
		this.limit = limit;
		this.spent = 0;
	}

	get left() { return this.limit - this.spent; }

	/** Refuses a size that has only been claimed, without taking it. */
	check(name, bytes) {
		if (bytes <= this.left) return;
		const mb = (n) => Math.round(n / 1048576);
		throw new ZipError(
			`'${name}' takes this archive past the ${mb(this.limit)} MB this reader `
			+ `will decompress in total: ${mb(this.spent)} MB have come out already and `
			+ `this entry adds ${mb(bytes)} more. No real project expands that far, so `
			+ `the archive is either damaged or built to exhaust memory.`,
		);
	}

	spend(name, bytes) {
		this.check(name, bytes);
		this.spent += bytes;
	}
}

const DEFERRED = Symbol('deferred');

/**
 * The entries of an archive: a Map of name to bytes, most of them produced on
 * the first `get` rather than on the way past.
 *
 * `unzip` used to inflate and retain every entry. An .eas assessment carries a
 * `simulation/` folder of result files that dwarfs the model it belongs to,
 * and the importer reads model.xml and the XML beside it and nothing else --
 * so all of that work, and all of the memory it held, was spent on bytes
 * nobody would ever look at.
 *
 * A deferred entry inflates with the bundled inflater, because `get` answers
 * synchronously and `DecompressionStream` does not. The XML is inflated up
 * front instead, where the platform's faster path is still available.
 */
class ZipEntries extends Map {
	/** Registers an entry to be produced when something asks for it. */
	defer(name, produce) {
		super.set(name, { [DEFERRED]: produce });
		return this;
	}

	get(name) {
		const held = super.get(name);
		if (!held || !held[DEFERRED]) return held;
		const bytes = held[DEFERRED]();
		super.set(name, bytes);
		return bytes;
	}

	// Every way of reading the values out goes through `get`, so an entry is
	// the same array however it is reached and is produced at most once.
	*[Symbol.iterator]() {
		for (const name of [...super.keys()]) yield [name, this.get(name)];
	}

	entries() { return this[Symbol.iterator](); }

	*values() { for (const [, bytes] of this) yield bytes; }

	forEach(fn, thisArg) {
		for (const [name, bytes] of this) fn.call(thisArg, bytes, name, this);
	}
}

const EOCD_SIG = 0x06054b50;
const EOCD64_LOCATOR_SIG = 0x07064b50;
const EOCD64_SIG = 0x06064b50;
const CD_SIG = 0x02014b50;
const LFH_SIG = 0x04034b50;

/**
 * @param {ArrayBuffer|Uint8Array} data
 * @param {{inflateLimit?: number}} [opts]  what the whole archive may inflate
 *   to; `MAX_ARCHIVE_INFLATED` unless a test says otherwise
 * @returns {Promise<Map<string, Uint8Array>>} entry name -> bytes
 */
export async function unzip(data, opts = {}) {
	const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
	const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

	const eocd = findEOCD(bytes, view);
	let { entryCount, cdOffset } = eocd;

	// ZIP64, for the rare enormous project.
	if (entryCount === 0xffff || cdOffset === 0xffffffff) {
		const z64 = findZip64(bytes, view, eocd.offset);
		if (z64) { entryCount = z64.entryCount; cdOffset = z64.cdOffset; }
	}

	const out = new ZipEntries();
	// One allowance for the whole archive, spent by every entry that inflates
	// -- including the ones that inflate later, on first access.
	const budget = new Budget(opts.inflateLimit ?? MAX_ARCHIVE_INFLATED);
	let p = cdOffset;

	for (let i = 0; i < entryCount; i++) {
		if (p < 0 || p + 46 > bytes.length || view.getUint32(p, true) !== CD_SIG) {
			throw new ZipError('The central directory is damaged');
		}
		const flags = view.getUint16(p + 8, true);
		const method = view.getUint16(p + 10, true);
		let compressedSize = view.getUint32(p + 20, true);
		let uncompressedSize = view.getUint32(p + 24, true);
		const nameLen = view.getUint16(p + 28, true);
		const extraLen = view.getUint16(p + 30, true);
		const commentLen = view.getUint16(p + 32, true);
		let localOffset = view.getUint32(p + 42, true);

		// The record's three variable parts have to fit too. `subarray` would
		// quietly clip a name that runs off the end, and the entry would then
		// be looked up -- and reported -- under a name the archive never gave it.
		if (p + 46 + nameLen + extraLen + commentLen > bytes.length) {
			throw new ZipError(
				`The central directory runs past the end of this ${bytes.length}-byte archive`,
			);
		}

		const nameBytes = bytes.subarray(p + 46, p + 46 + nameLen);
		const name = decodeName(nameBytes);

		if (flags & 0x01) {
			throw new ZipError(
				`'${name}' is encrypted. Ecolego can obfuscate a project on save; ` +
				`re-save it without that option, or export the model, before importing.`,
			);
		}

		// ZIP64 extended information, when the 32-bit fields are saturated.
		if (compressedSize === 0xffffffff || uncompressedSize === 0xffffffff
			|| localOffset === 0xffffffff) {
			const extra = readZip64Extra(
				view, p + 46 + nameLen, extraLen,
				{ compressedSize, uncompressedSize, localOffset }, name,
			);
			compressedSize = extra.compressedSize;
			uncompressedSize = extra.uncompressedSize;
			localOffset = extra.localOffset;
		}

		p += 46 + nameLen + extraLen + commentLen;

		if (name.endsWith('/')) continue; // a directory entry

		// Every one of these numbers came out of the file, and a file is
		// entitled to lie. `DataView` answers an out-of-range read with a
		// RangeError from inside the standard library, which reaches the user
		// as "Offset is outside the bounds of the DataView" -- true, and
		// useless. Checked here instead, so a damaged archive is reported as a
		// damaged archive.
		if (localOffset < 0 || localOffset + 30 > bytes.length) {
			throw new ZipError(
				`'${name}' says its data begins at byte ${localOffset}, which is `
				+ `outside this ${bytes.length}-byte archive.`,
			);
		}
		// The local header repeats the name and extra field, and its extra
		// field length can differ from the central one.
		if (view.getUint32(localOffset, true) !== LFH_SIG) {
			throw new ZipError(`The local header for '${name}' is damaged`);
		}
		const lNameLen = view.getUint16(localOffset + 26, true);
		const lExtraLen = view.getUint16(localOffset + 28, true);
		const dataStart = localOffset + 30 + lNameLen + lExtraLen;
		if (dataStart > bytes.length || dataStart + compressedSize > bytes.length) {
			throw new ZipError(
				`'${name}' claims ${compressedSize} bytes from ${dataStart}, which `
				+ `runs past the end of this ${bytes.length}-byte archive.`,
			);
		}
		const raw = bytes.subarray(dataStart, dataStart + compressedSize);

		if (method === 0) {
			// Stored data cannot expand, so it is outside the budget: it is
			// already in the archive and bounded by it. Deferred all the same,
			// because a copy nobody asked for is still a copy.
			out.defer(name, () => raw.slice());
		} else if (method === 8) {
			// The XML is what the importer reads, and so the only thing worth
			// the platform's asynchronous inflater. Everything else waits
			// until something asks for it -- see ZipEntries.
			if (/\.xml$/i.test(name)) {
				out.set(name, await inflateEntry(raw, uncompressedSize, name, budget));
			} else {
				out.defer(name, () => inflateEntrySync(raw, uncompressedSize, name, budget));
			}
		} else {
			throw new ZipError(
				`'${name}' uses compression method ${method}, which is not supported ` +
				`(only stored and deflate are).`,
			);
		}
	}

	return out;
}

function findEOCD(bytes, view) {
	// The end-of-central-directory record sits in the last 64KB, after a
	// variable-length comment.
	const min = Math.max(0, bytes.length - 0x10000 - 22);
	for (let p = bytes.length - 22; p >= min; p--) {
		if (view.getUint32(p, true) === EOCD_SIG) {
			return {
				offset: p,
				entryCount: view.getUint16(p + 10, true),
				cdOffset: view.getUint32(p + 16, true),
			};
		}
	}
	throw new ZipError(
		'This does not look like a ZIP archive. An Ecolego project (.eco) is a ' +
		'zipped project folder; a bare model.xml should be opened directly instead.',
	);
}

/**
 * The ZIP64 end record, for the rare enormous project.
 *
 * Every offset read here is a number out of the file, and the two functions
 * below used to believe all of them. An unchecked `DataView` read answers with
 * a RangeError from inside the standard library, so a crafted archive reported
 * itself as "Offset is outside the bounds of the DataView" -- exactly the
 * message the checks in `unzip` were written to keep away from the user,
 * arriving by the one route that had none of its own.
 */
function findZip64(bytes, view, eocdOffset) {
	const locator = eocdOffset - 20;
	if (locator < 0 || locator + 20 > bytes.length) return null;
	if (view.getUint32(locator, true) !== EOCD64_LOCATOR_SIG) return null;
	const at = view.getBigUint64(locator + 8, true);
	const z64 = Number(at);
	// 56 bytes: through the central directory offset, the last field wanted.
	if (!Number.isSafeInteger(z64) || z64 < 0 || z64 + 56 > bytes.length) {
		throw new ZipError(
			`This archive says its ZIP64 directory is at byte ${at}, which is outside `
			+ `its own ${bytes.length} bytes.`,
		);
	}
	if (view.getUint32(z64, true) !== EOCD64_SIG) return null;
	return {
		entryCount: Number(view.getBigUint64(z64 + 32, true)),
		cdOffset: Number(view.getBigUint64(z64 + 48, true)),
	};
}

function readZip64Extra(view, start, length, current, name) {
	let p = start;
	// The extra field's length is a number in the file too, and the records
	// inside it carry lengths of their own, so the walk is clamped to the
	// archive and each 64-bit read is checked against the record it is in.
	const end = Math.min(start + length, view.byteLength);
	const out = { ...current };
	while (p + 4 <= end) {
		const id = view.getUint16(p, true);
		const size = view.getUint16(p + 2, true);
		if (id === 0x0001) {
			let q = p + 4;
			const stop = Math.min(p + 4 + size, end);
			const next = () => {
				if (q + 8 > stop) {
					throw new ZipError(
						`The ZIP64 record for '${name}' says it is ${size} bytes long but `
						+ `does not hold the sizes it promises; the archive looks damaged.`,
					);
				}
				const v = Number(view.getBigUint64(q, true));
				q += 8;
				return v;
			};
			if (out.uncompressedSize === 0xffffffff) out.uncompressedSize = next();
			if (out.compressedSize === 0xffffffff) out.compressedSize = next();
			if (out.localOffset === 0xffffffff) out.localOffset = next();
			break;
		}
		p += 4 + size;
	}
	return out;
}

function decodeName(nameBytes) {
	// Bit 11 of the flags means the name is UTF-8, and without it the spec
	// says CP437. There used to be a branch on that bit which decoded UTF-8
	// down both arms -- a ternary with nothing in it. UTF-8 is kept, on
	// purpose and unconditionally: CP437 needs a 128-entry table TextDecoder
	// does not carry, its low half is ASCII and so identical to UTF-8, and
	// every name in these archives is ASCII, because the writer emits
	// UTF-8 and sets the flag. A high byte in an unflagged name therefore
	// comes back as U+FFFD, which garbles that name in the "the archive
	// holds:" message and does nothing else -- model.xml is matched on its
	// basename, and that cannot contain one.
	return new TextDecoder('utf-8').decode(nameBytes);
}

/**
 * `deflate-raw` is a recent addition to DecompressionStream -- Node gained it
 * after 20.10, older Safari lacks it -- so we probe once and fall back to the
 * bundled inflate. The native path is preferred where present because it is
 * substantially faster on large archives.
 */
let nativeRawDeflate = null;
function hasNativeRawDeflate() {
	if (nativeRawDeflate !== null) return nativeRawDeflate;
	try {
		if (typeof DecompressionStream === 'undefined') {
			nativeRawDeflate = false;
		} else {
			// eslint-disable-next-line no-new
			new DecompressionStream('deflate-raw');
			nativeRawDeflate = true;
		}
	} catch {
		nativeRawDeflate = false;
	}
	return nativeRawDeflate;
}

/**
 * How much this entry may produce: the smaller of the per-entry cap and what
 * is left of the archive's budget, with the directory's own claim refused
 * before a byte is decompressed. A declared size costs nothing to inspect and
 * everything to believe.
 */
function allowanceFor(expectedSize, name, budget) {
	if (expectedSize > MAX_INFLATED) {
		throw new ZipError(
			`'${name}' says it expands to ${Math.round(expectedSize / 1048576)} MB, `
			+ `past the ${Math.round(MAX_INFLATED / 1048576)} MB this reader will `
			+ `decompress. No real model is that large.`,
		);
	}
	budget.check(name, expectedSize);
	return Math.min(MAX_INFLATED, budget.left);
}

/** Charges what actually came out, and checks it against the directory. */
function accept(buf, expectedSize, name, budget) {
	budget.spend(name, buf.length);
	if (expectedSize && buf.length !== expectedSize) {
		throw new ZipError(
			`'${name}' inflated to ${buf.length} bytes but the directory says ` +
			`${expectedSize}; the archive looks damaged.`,
		);
	}
	return buf;
}

async function inflateEntry(raw, expectedSize, name, budget) {
	const limit = allowanceFor(expectedSize, name, budget);
	let buf;
	try {
		if (hasNativeRawDeflate()) {
			// The browser's own inflater is not bounded either, so the stream
			// is cut off at the cap rather than read to the end. A zip bomb is
			// a small file: the compressed side says nothing about how much
			// comes out.
			const stream = new Blob([raw]).stream()
				.pipeThrough(new DecompressionStream('deflate-raw'))
				.pipeThrough(cappedAt(limit, name));
			buf = new Uint8Array(await new Response(stream).arrayBuffer());
		} else {
			buf = inflateRawJS(raw, expectedSize, limit);
		}
	} catch (e) {
		if (e instanceof ZipError) throw e;
		throw new ZipError(`Could not decompress '${name}': ${e.message}`);
	}
	return accept(buf, expectedSize, name, budget);
}

/**
 * The same, for an entry inflated on first access. `get` answers
 * synchronously, so this path is the bundled inflater's alone -- see
 * ZipEntries.
 */
function inflateEntrySync(raw, expectedSize, name, budget) {
	const limit = allowanceFor(expectedSize, name, budget);
	let buf;
	try {
		buf = inflateRawJS(raw, expectedSize, limit);
	} catch (e) {
		if (e instanceof ZipError) throw e;
		throw new ZipError(`Could not decompress '${name}': ${e.message}`);
	}
	return accept(buf, expectedSize, name, budget);
}

/**
 * A transform that passes bytes through and fails past a total.
 *
 * `new Response(stream).arrayBuffer()` will happily assemble tens of
 * gigabytes; this is what stops it, at the same cap the JavaScript inflater
 * uses so that the two paths refuse the same archives.
 */
function cappedAt(limit, name) {
	let total = 0;
	return new TransformStream({
		transform(chunk, controller) {
			total += chunk.byteLength;
			if (total > limit) {
				controller.error(new InflateError(
					`'${name}' expands past the ${Math.round(limit / 1048576)} MB left for `
					+ `it, which is far more than any real model -- the archive is either `
					+ `damaged or built to exhaust memory`,
				));
				return;
			}
			controller.enqueue(chunk);
		},
	});
}

/** Decodes an entry as UTF-8 text. */
export function entryText(bytes) {
	return new TextDecoder('utf-8').decode(bytes);
}

// --- writing ------------------------------------------------------------------

/**
 * CRC-32, which a ZIP entry carries and a reader checks.
 *
 * The table is built once on first use rather than written out: 256 entries of
 * hex would be a screenful of numbers nobody can check by eye, and the
 * polynomial they come from is one line that can be.
 */
let crcTable = null;

export function crc32(bytes) {
	if (!crcTable) {
		crcTable = new Uint32Array(256);
		for (let n = 0; n < 256; n++) {
			let c = n;
			// 0xedb88320 is the reversed form of the CRC-32 polynomial, which
			// is the form a right-shifting implementation needs.
			for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
			crcTable[n] = c >>> 0;
		}
	}
	let c = 0xffffffff;
	for (let i = 0; i < bytes.length; i++) c = crcTable[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
	return (c ^ 0xffffffff) >>> 0;
}

/** Runs bytes through one of `CompressionStream`'s formats, or null. */
async function compress(bytes, format) {
	try {
		const out = new Response(
			new Blob([bytes]).stream().pipeThrough(new CompressionStream(format)),
		);
		return new Uint8Array(await out.arrayBuffer());
	} catch {
		return null;
	}
}

/**
 * Deflate, in the raw form a ZIP entry holds.
 *
 * Two routes, because `deflate-raw` is newer than `deflate` and not everywhere
 * yet -- Node 20 has the second and not the first, which is how this was
 * found: the archive came out 2% *larger* than the JSON in it, because every
 * entry had quietly fallen back to stored.
 *
 * The second route is zlib's own framing with the framing removed. A zlib
 * stream is a two-byte header, the raw deflate data, and a four-byte Adler-32:
 * take the middle and it is exactly what a ZIP entry wants. Safe because
 * `CompressionStream` never sets a preset dictionary, which is the one thing
 * that would make the header longer than two bytes.
 *
 * Null when neither is available, and the caller stores instead. A correct
 * archive that is larger than it needs to be beats a save that fails.
 */
async function deflateRaw(bytes) {
	if (typeof CompressionStream === 'undefined') return null;
	const direct = await compress(bytes, 'deflate-raw');
	if (direct) return direct;
	const wrapped = await compress(bytes, 'deflate');
	if (!wrapped || wrapped.length < 7) return null;
	return wrapped.subarray(2, wrapped.length - 4);
}

/**
 * One or more entries, as a ZIP archive.
 *
 * Enough of the format to be read by anything -- local headers, deflate or
 * stored data, a central directory and an end record. No ZIP64: an entry is
 * refused past 4 GB rather than written in a form half the tools in the world
 * would not open, and the largest model here is 35 MB before it is compressed.
 *
 * Sizes are known before anything is written, so there are no data descriptors
 * and the local header is complete -- which is the shape the widest range of
 * readers, including this file's own, handles without special cases.
 *
 * **What is written is what `unzip` will read back.** The reader stops at
 * `MAX_ARCHIVE_INFLATED` of deflated data for the whole archive, and a run
 * saved with its model can be larger than that -- so Save wrote archives that
 * Open refused. An entry that would take the deflated total past the reader's
 * allowance is stored instead: stored data is outside it, being already in the
 * archive and bounded by it. The file is larger, and it opens.
 *
 * `store` writes every entry stored. Deflate is the platform's, and platforms'
 * encoders choose different bytes for the same data; stored entries are the
 * same archive wherever it is made, which is what the .eco export wants
 * (see ./ecoexport.js).
 *
 * @param {Array<{name: string, bytes: Uint8Array}>} entries
 * @param {{modified?: Date, inflateLimit?: number, store?: boolean}} [opts]
 *   `inflateLimit` is the reader's allowance, `MAX_ARCHIVE_INFLATED` unless a
 *   test says otherwise
 * @returns {Promise<Uint8Array>}
 */
export async function zip(entries, opts = {}) {
	const when = dosTime(opts.modified ?? new Date(0));
	const limit = opts.store ? -1 : opts.inflateLimit ?? MAX_ARCHIVE_INFLATED;
	const local = [];
	const central = [];
	let offset = 0;
	let inflated = 0;

	for (const entry of entries) {
		const name = new TextEncoder().encode(entry.name);
		const raw = entry.bytes;
		if (raw.length > 0xffffffff) {
			throw new ZipError(`'${entry.name}' is ${raw.length} bytes, which needs ZIP64 `
				+ 'and is more than this writer will produce.');
		}
		// Stored when deflate did not help, which happens for something already
		// compressed and for the empty file -- and when the reader would not
		// inflate this much more of one archive. Not compressed at all then:
		// deflating a hundred megabytes to throw the answer away is time.
		const fits = inflated + raw.length <= limit;
		const packed = fits ? await deflateRaw(raw) : null;
		const useDeflate = packed != null && packed.length < raw.length;
		if (useDeflate) inflated += raw.length;
		const data = useDeflate ? packed : raw;
		const method = useDeflate ? 8 : 0;
		const sum = crc32(raw);

		const lfh = new Uint8Array(30 + name.length);
		const lv = new DataView(lfh.buffer);
		lv.setUint32(0, LFH_SIG, true);
		lv.setUint16(4, 20, true);          // version needed: 2.0, for deflate
		lv.setUint16(6, 0x0800, true);      // the name is UTF-8
		lv.setUint16(8, method, true);
		lv.setUint16(10, when.time, true);
		lv.setUint16(12, when.date, true);
		lv.setUint32(14, sum, true);
		lv.setUint32(18, data.length, true);
		lv.setUint32(22, raw.length, true);
		lv.setUint16(26, name.length, true);
		lfh.set(name, 30);

		const cdh = new Uint8Array(46 + name.length);
		const cv = new DataView(cdh.buffer);
		cv.setUint32(0, CD_SIG, true);
		cv.setUint16(4, 20, true);          // version made by
		cv.setUint16(6, 20, true);          // version needed
		cv.setUint16(8, 0x0800, true);
		cv.setUint16(10, method, true);
		cv.setUint16(12, when.time, true);
		cv.setUint16(14, when.date, true);
		cv.setUint32(16, sum, true);
		cv.setUint32(20, data.length, true);
		cv.setUint32(24, raw.length, true);
		cv.setUint16(28, name.length, true);
		cv.setUint32(42, offset, true);
		cdh.set(name, 46);

		local.push(lfh, data);
		central.push(cdh);
		offset += lfh.length + data.length;
	}

	const cdSize = central.reduce((n, c) => n + c.length, 0);
	const eocd = new Uint8Array(22);
	const ev = new DataView(eocd.buffer);
	ev.setUint32(0, EOCD_SIG, true);
	ev.setUint16(8, entries.length, true);
	ev.setUint16(10, entries.length, true);
	ev.setUint32(12, cdSize, true);
	ev.setUint32(16, offset, true);

	const parts = [...local, ...central, eocd];
	const total = parts.reduce((n, p) => n + p.length, 0);
	const out = new Uint8Array(total);
	let at = 0;
	for (const p of parts) { out.set(p, at); at += p.length; }
	return out;
}

/**
 * A date and time in the form a ZIP entry carries: MS-DOS, two seconds of
 * resolution, and no year before 1980.
 *
 * The default is the epoch, which lands on 1980-01-01 -- deliberately, so that
 * saving the same model twice gives the same bytes. A file whose checksum
 * changes when nothing in it did is a file nobody can compare.
 */
function dosTime(d) {
	const year = Math.max(1980, d.getFullYear());
	return {
		date: ((year - 1980) << 9) | ((d.getMonth() + 1) << 5) | Math.max(1, d.getDate()),
		time: (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1),
	};
}
