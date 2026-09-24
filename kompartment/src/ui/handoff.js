/**
 * Handing a result file to the HDF5 browser without it touching the disk.
 *
 * The result browser at kvotab.se already accepts a file this way -- see
 * `resources/js/rb-handoff.js` there -- and this is the other half of that
 * protocol. A tab is opened with a `#handoff=<our origin>` hash, it announces
 * itself with `rb-ready` once it is listening, and the bytes go across as a
 * transferred `ArrayBuffer`: no copy, no download, no file for the user to find
 * again afterwards.
 *
 * **The window is opened before the file exists, and that is not an accident.**
 * A pop-up is only allowed out of a user gesture, and building a result --
 * fetching realisation matrices from the worker, writing the tree -- is
 * asynchronous and can take seconds. Opening the tab inside the click and
 * sending to it later is the only order that works. `open()` therefore returns
 * something to send *to*, and `send` waits for the far side to be ready.
 *
 * **The receiving page decides whether to accept us.** Its allow-list is
 * same-origin by default, so a page served from anywhere else has to be named
 * in `RB_HANDOFF_ALLOWED_ORIGINS` over there. Nothing here can change that, and
 * the failure is quiet by design -- the far side logs and ignores -- so this
 * gives up after a timeout and says what is likely wrong rather than waiting
 * for a reply that will never come.
 */

/**
 * Where the reader lives. `?rb=<url>` overrides it, which is how it is tested
 * and how a local copy is used.
 *
 * **The canonical address, with no `www`.** `www.kvotab.se/rb.html` answers,
 * and 301s to `kvotab.se/rb.html` -- so the tab ends up on an origin that is
 * not the one this page opened, and the handshake cannot survive that: the
 * ready ping arrives from `https://kvotab.se` and is ignored for coming from
 * the wrong place, and the file is posted to `https://www.kvotab.se` and
 * silently discarded for going to the wrong place. Both halves fail in
 * silence, because that is exactly what an origin check is for. A redirect is
 * invisible here and has to be kept out by using the address the reader
 * actually serves from.
 */
export const RESULT_BROWSER = 'https://kvotab.se/rb.html';

/**
 * Where an override is allowed to point.
 *
 * Three places, and nowhere else: the reader itself, anything on this page's
 * own origin, and anything on loopback -- which between them are every way a
 * local `rb.html` is actually reached, and the only reason the override
 * exists.
 *
 * **This is a query parameter deciding where a file is sent.** `?rb=` was
 * taken as written, so a link to `index.html?rb=https://somewhere.else/x` made
 * the page open that address, hand it `window.opener`, and post the reader's
 * complete result file to it -- a whole assessment's realisations, on one
 * click of *Open in the HDF5 Browser*, with nothing on screen to say where it
 * had gone. `?model=` has always been checked against the list of examples;
 * this is the same check, and it belongs here rather than at the call site
 * because `browserURL` is what everything asks.
 */
export const ALLOWED_BROWSERS = [RESULT_BROWSER];

/** Hosts that mean "this machine". */
const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);

/**
 * The address to open, with any override applied *if it is allowed*.
 *
 * @param {string} [search]  the query string to read `rb` from
 * @param {string} [base]    what counts as "here", for the same-origin case
 * @returns {string} the address, and the canonical one when the override is
 *   refused -- refusing by falling back rather than by throwing, because an
 *   address nobody should have written is not a reason to take away a button.
 */
export function browserURL(
	search = (typeof location === 'undefined' ? '' : location.search),
	base = (typeof location === 'undefined' ? RESULT_BROWSER : location.href),
) {
	const override = new URLSearchParams(search).get('rb');
	if (!override) return RESULT_BROWSER;
	let url;
	try {
		url = new URL(override, base);
	} catch {
		return RESULT_BROWSER;
	}
	// Its own origin -- a copy served beside this page.
	let here = null;
	try { here = new URL(base).origin; } catch { /* no origin to compare to */ }
	if (here && url.origin === here) return url.href;
	// The reader, wherever on its own origin it is put.
	if (ALLOWED_BROWSERS.some((a) => url.href === a || url.origin === new URL(a).origin)) {
		return url.href;
	}
	// A copy on this machine. Which is the case the override exists for: a
	// local `rb.html` is usually on a different port from the editor, so
	// same-origin alone would have taken the override away from the only
	// people who use it. Loopback is not a reachable destination for anyone
	// sending a link -- it means the reader's own machine, and something
	// already running on it has no need of this.
	if (LOOPBACK.has(url.hostname)) return url.href;
	return RESULT_BROWSER;
}

/**
 * The name a result file is handed over under.
 *
 * The far side sanitises this itself, and appends `.h5` if it has to; this
 * only has to produce something a person recognises in the tab it opens.
 */
export function handoffName(modelName, suffix = '') {
	const base = String(modelName ?? '').trim() || 'results';
	return `${base}${suffix}.h5`.replace(/[\\/]/g, '_');
}

/**
 * Opens the browser and returns a handle to send a file to it.
 *
 * @param {object} [opts]
 * @param {string} [opts.url]      where the browser is
 * @param {number} [opts.timeout]  how long to wait for `rb-ready`, then for the
 *                                 file to be acknowledged
 * @param {Window} [opts.host]     the window to open from; for tests
 * @returns {{send: (name: string, bytes: Uint8Array) => Promise<string[]>,
 *   cancel: () => void, window: Window}|null}  null when the pop-up was blocked
 */
export function openHandoff({
	url = browserURL(), timeout = 45000, host = (typeof window === 'undefined' ? null : window),
} = {}) {
	if (!host) return null;
	const base = String(url).split('#')[0];
	const origin = new URL(base, host.location.href).origin;
	const target = `${base}#handoff=${encodeURIComponent(host.location.origin)}`;
	const win = host.open(target, '_blank');
	// Blocked, or opened into something that cannot be posted to. Reported as
	// null rather than thrown: it is an ordinary thing for a browser to do and
	// the caller has a better sentence to say about it than this does.
	if (!win) return null;

	let ready = false;
	let onReady = null;
	let settle = null;

	const listen = (ev) => {
		if (ev.origin !== origin || !ev.data || typeof ev.data !== 'object') return;
		const { kvot } = ev.data;
		if (kvot === 'rb-ready') {
			ready = true;
			onReady?.();
			return;
		}
		if (kvot === 'rb-opened') settle?.({ ok: true, names: ev.data.names ?? [] });
		if (kvot === 'rb-error') settle?.({ ok: false, message: ev.data.message ?? '' });
	};
	host.addEventListener('message', listen);
	const cancel = () => { host.removeEventListener('message', listen); };

	const waitReady = () => (ready ? Promise.resolve(true) : new Promise((resolve) => {
		const timer = setTimeout(() => { onReady = null; resolve(false); }, timeout);
		onReady = () => { clearTimeout(timer); resolve(true); };
	}));

	const send = async (name, bytes) => {
		if (!await waitReady()) {
			cancel();
			// Three things make this happen and none of them says so on its
			// own, so the message names all three. The origin is in it because
			// a redirect -- `www.` to bare, http to https -- lands the tab
			// somewhere else and every message after that is dropped without
			// a word by design.
			throw new Error(`No answer from ${origin}. It may still be loading; the `
				+ 'address may be redirecting somewhere else, which the handshake '
				+ `cannot survive; or the reader may not accept files from `
				+ `${host.location.origin} — that is a list inside it.`);
		}
		// Transferred, not copied: a realisation matrix is the one export that
		// can be hundreds of megabytes, and a structured clone of it would be
		// a second copy on a page that is already holding the first.
		const buffer = bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength
			? bytes.buffer
			: bytes.slice().buffer;
		const done = new Promise((resolve) => {
			const timer = setTimeout(
				() => resolve({ ok: false, message: 'it did not say whether the file opened' }),
				timeout);
			settle = (r) => { clearTimeout(timer); settle = null; resolve(r); };
		});
		win.postMessage({ kvot: 'rb-open', name, buffer }, origin, [buffer]);
		const result = await done;
		cancel();
		if (!result.ok) throw new Error(result.message || 'the result browser refused the file');
		return result.names;
	};

	return { send, cancel, window: win };
}
