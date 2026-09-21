/**
 * gzip, for a model file that has been through `gzip` or is going to be.
 *
 * The other compressed form a project arrives in. A ZIP is what you get from
 * the Save dialog and what double-clicks open on every desktop; `.json.gz` is
 * what you get from a command line, and somebody who keeps assessments in a
 * repository or ships them between machines will have made one. Reading both
 * costs almost nothing, and refusing one of them for no reason is the kind of
 * gap that makes a tool annoying.
 *
 * The platform's own `CompressionStream`/`DecompressionStream` do the work.
 * For reading there is a fallback, because a model that will not open is worse
 * than one that opens slowly: gzip is a short header, a raw DEFLATE stream and
 * a checksum, so the header is stripped here and ./inflate.js -- which this
 * project already carries for the ZIP reader -- does the rest. For *writing*
 * there is no fallback and none is needed: a platform too old to compress can
 * save the model uncompressed, which is what it did before any of this.
 */

import { inflateRaw, MAX_INFLATED } from './inflate.js';

export class GzipError extends Error {
	constructor(message) {
		super(message);
		this.name = 'GzipError';
	}
}

/** The two bytes every gzip member starts with. */
export const MAGIC = [0x1f, 0x8b];

/** Whether these bytes begin a gzip member. */
export function isGzip(bytes) {
	return bytes?.length >= 2 && bytes[0] === MAGIC[0] && bytes[1] === MAGIC[1];
}

/**
 * Decompresses a gzip member.
 *
 * @param {Uint8Array} bytes
 * @param {number} [limit] the most it may expand to
 * @returns {Promise<Uint8Array>}
 */
export async function gunzip(bytes, limit = MAX_INFLATED) {
	if (!isGzip(bytes)) throw new GzipError('This is not a gzip file.');
	if (typeof DecompressionStream !== 'undefined') {
		try {
			const out = new Response(
				new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')),
			);
			const buf = new Uint8Array(await out.arrayBuffer());
			if (buf.length > limit) {
				throw new GzipError(`This file expands to more than `
					+ `${Math.round(limit / 1048576)} MB, which is more than a tab can hold.`);
			}
			return buf;
		} catch (e) {
			if (e instanceof GzipError) throw e;
			// Fall through: the platform has the constructor but choked, and
			// the reader below can still try.
		}
	}
	return inflateRaw(afterHeader(bytes), sizeFromTrailer(bytes), limit);
}

/**
 * Where the DEFLATE data starts: past the ten fixed bytes and whichever of the
 * four optional fields the flags say are there.
 *
 * RFC 1952 §2.3. Nothing here writes any of them, but `gzip` on a command line
 * writes the file name as a matter of course, so a file made the obvious way
 * has FNAME set and a reader that assumed ten bytes would read rubbish.
 */
function afterHeader(bytes) {
	if (bytes.length < 18) throw new GzipError('This gzip file is truncated.');
	const flags = bytes[3];
	let at = 10;
	if (flags & 0x04) {                       // FEXTRA: a length and that many bytes
		at += 2 + (bytes[at] | (bytes[at + 1] << 8));
	}
	const skipString = () => {
		while (at < bytes.length && bytes[at] !== 0) at++;
		at++;
	};
	if (flags & 0x08) skipString();           // FNAME
	if (flags & 0x10) skipString();           // FCOMMENT
	if (flags & 0x02) at += 2;                // FHCRC
	if (at >= bytes.length - 8) throw new GzipError('This gzip file is truncated.');
	// The last eight bytes are the CRC-32 and the size, not data.
	return bytes.subarray(at, bytes.length - 8);
}

/**
 * The size in the trailer, which is the uncompressed length modulo 2^32.
 *
 * A hint for the inflater to size its buffer with, never a promise: it is four
 * bytes for a length that may not fit in four bytes, and it comes out of the
 * file, so it is checked against the limit like anything else would be.
 */
function sizeFromTrailer(bytes) {
	const n = bytes.length;
	return (bytes[n - 4] | (bytes[n - 3] << 8) | (bytes[n - 2] << 16) | (bytes[n - 1] << 24)) >>> 0;
}

/**
 * Compresses to a gzip member, or null where the platform will not.
 *
 * Null rather than a throw: the caller's answer to "this browser cannot
 * compress" is to write the file uncompressed, which is a save that works.
 *
 * @param {Uint8Array} bytes
 * @returns {Promise<Uint8Array|null>}
 */
export async function gzip(bytes) {
	if (typeof CompressionStream === 'undefined') return null;
	try {
		const out = new Response(
			new Blob([bytes]).stream().pipeThrough(new CompressionStream('gzip')),
		);
		return new Uint8Array(await out.arrayBuffer());
	} catch {
		return null;
	}
}
