/**
 * A model as a link: the whole file, compressed, in the part of an address
 * after the `#`.
 *
 * The part after the `#` is never sent to a server -- a browser keeps it to
 * itself -- so a link like this carries a model from one person to another
 * with nothing in between knowing what is in it, and it works from a page
 * served by anything, this site's static pages included. It is what *Share* on
 * the App designer tab makes: the model with its app, opened as the app.
 *
 * `#m=` then the model's JSON, compressed with raw DEFLATE and written in the
 * base64 that addresses allow (`-` and `_` for `+` and `/`, no padding).
 * Compressed by the platform (`CompressionStream`), read back by this tool's
 * own inflater, which bounds what the text may expand to: a link is a file
 * somebody else wrote, and is read as one.
 *
 * How long a link may be is the browser's to say, and the programs it is sent
 * through: Chrome takes two megabytes of address; some mail programs break a
 * link at a few thousand characters. `linkAdvice` says which side of those a
 * link is.
 */

import { inflateRaw } from './inflate.js';

/** The key the model goes under, after the `#`. */
export const LINK_KEY = 'm';

/** Past this, no browser is sure to take the address. */
export const LINK_MAX = 2000000;

/** Past this, some mail and chat programs break or shorten a link. */
export const LINK_LONG = 8000;

/** What a link's model may expand to: far more than any model that fits in one. */
const INFLATE_LIMIT = 64 * 1024 * 1024;

/** Bytes to base64 for an address: `-` and `_`, and no `=`. */
export function toBase64Url(bytes) {
	let bin = '';
	// In pieces: one call over a megabyte of arguments is past what an engine
	// takes in a call.
	for (let i = 0; i < bytes.length; i += 0x8000) {
		bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
	}
	return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** And back; null for text that is not base64 of either kind. */
export function fromBase64Url(text) {
	const s = String(text ?? '').replace(/-/g, '+').replace(/_/g, '/');
	if (!/^[A-Za-z0-9+/]*$/.test(s)) return null;
	let bin;
	try {
		bin = atob(s + '='.repeat((4 - (s.length % 4)) % 4));
	} catch {
		return null; // not base64 after all
	}
	const out = new Uint8Array(bin.length);
	for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
	return out;
}

/**
 * The model, as the text that goes after `#m=`.
 *
 * @returns {Promise<string>}
 * @throws where the platform cannot compress, which every browser this tool
 *   runs in can
 */
export async function encodeModel(raw) {
	if (typeof CompressionStream === 'undefined') {
		throw new Error('This browser cannot compress, so it cannot make a link.');
	}
	const bytes = new TextEncoder().encode(JSON.stringify(raw));
	const squeeze = async (format) => new Uint8Array(await new Response(
		new Blob([bytes]).stream().pipeThrough(new CompressionStream(format))).arrayBuffer());
	let deflated;
	try {
		deflated = await squeeze('deflate-raw');
	} catch {
		// A platform without the raw format has the zlib one, which is the same
		// stream inside two bytes of header and four of checksum.
		const z = await squeeze('deflate');
		deflated = z.subarray(2, z.length - 4);
	}
	return toBase64Url(deflated);
}

/**
 * A model out of a link's text, or an error that says why not.
 *
 * @param {string} text  what follows `#m=`
 * @returns {object}
 */
export function decodeModel(text) {
	const bytes = fromBase64Url(text);
	if (!bytes || !bytes.length) throw new Error('The link holds no model: the part after “#m=” is not one.');
	let json;
	try {
		json = new TextDecoder('utf-8', { fatal: true }).decode(inflateRaw(bytes, 0, INFLATE_LIMIT));
	} catch (e) {
		throw new Error(`The link’s model could not be read: ${e?.message ?? e}. It may have been cut short on the way.`);
	}
	let model;
	try {
		model = JSON.parse(json);
	} catch {
		throw new Error('The link’s model is not a model file: it was cut short, or changed, on the way.');
	}
	if (!model || typeof model !== 'object' || Array.isArray(model)) {
		throw new Error('The link’s model is not a model file.');
	}
	return model;
}

/** The model's text in an address's `#`, or null when there is none. */
export function modelInHash(hash) {
	const m = new RegExp(`^#?(?:.*&)?${LINK_KEY}=([^&]*)`).exec(String(hash ?? ''));
	return m ? m[1] : null;
}

/**
 * The link: `base`, with `?app` when it is to open as the app, and the model
 * after the `#`. Whatever else `base` carried in its address is dropped --
 * it is this page's own, and the link is the model's.
 */
export function linkFor(base, payload, { app = true } = {}) {
	const url = new URL(base);
	url.search = '';
	if (app) url.searchParams.set('app', '');
	url.hash = `${LINK_KEY}=${payload}`;
	// `?app=` reads as it is meant, `?app`.
	return url.href.replace('?app=#', '?app#');
}

/** What to say about a link's length. */
export function linkAdvice(length) {
	if (length > LINK_MAX) return { ok: false, tone: 'warn', text: 'Too long for a link: no browser is sure to take an address this long. Send the model file instead.' };
	if (length > LINK_LONG) return { ok: true, tone: 'warn', text: 'Long for a link: a browser takes it, but some mail and chat programs break or shorten a link this long. Pasted whole, it works.' };
	return { ok: true, tone: 'info', text: 'Short enough to go anywhere a link goes.' };
}
