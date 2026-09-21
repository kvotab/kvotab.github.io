/**
 * The block clipboard, shared between tabs.
 *
 * The clipboard itself is `state.clipboard` in app.js: a set of blocks with
 * their equations, their per-index values and the connections between them,
 * taken by `copySelection` and put back by `pasteBlocks`. That object lives in
 * one page, which is enough to carry blocks from one model to the next *in
 * that tab* -- load another model and paste -- and no help at all when the two
 * models are open side by side in two tabs, which is how anybody actually
 * compares them.
 *
 * So the same payload is written here as well. Two tabs of this application
 * are two pages of one origin, and `localStorage` is the one thing they both
 * see: a copy in either is a paste in the other, and neither has to know the
 * other exists.
 *
 * **The in-page copy is still the real one.** This is a second place the same
 * thing is written, not a replacement: a paste in the tab that did the copy
 * must not depend on storage being available, and a browser with site data
 * switched off still has a working clipboard within its tab. What this adds is
 * *reach*, and everything about it degrades to nothing.
 *
 * **Whichever copy is newer wins**, which is what a clipboard means: the last
 * thing copied anywhere is the thing that pastes. Each record carries the
 * moment it was written, and app.js compares that against its own.
 *
 * **It can decline, and says so.** `localStorage` is a few megabytes over the
 * whole origin, shared with the draft the autosave keeps -- and a copy of a
 * landscape sub-system is megabytes on its own. Past the ceiling the payload
 * is not shared: the copy still works in the tab that made it, and the message
 * says the other tabs will not see it. Silently not sharing would be worse,
 * because the failure shows up as a paste that produces the wrong blocks.
 *
 * **What is at rest here.** Part of a model, in this browser, under this
 * origin, until something else is copied. The autosave already keeps the whole
 * model in the same place for the same reasons; `forget()` is here for a
 * reader who wants it gone before they walk away.
 */

/**
 * Where it lives. Versioned, so a payload of an older shape is ignored.
 *
 * **A storage key does not follow the product's name.** It is where a reader's
 * work is, and renaming it throws that work away in every browser that has any
 * -- silently, since the new name simply finds nothing. The draft's key
 * (`ecolego.draft.v1`, in autosave.js) is one rename older still and stays for
 * the same reason. A key is changed only when what is *under* it changes, and
 * then by bumping the version at the end.
 */
const KEY = 'boxflow.clipboard.v1';

/**
 * The most a shared copy may be, serialised.
 *
 * Smaller than the draft's ceiling, and deliberately: the draft is the
 * reader's work and the first thing the quota should be spent on. A copy that
 * does not fit is a copy that still pastes in the tab it was taken in.
 */
export const MOST = 1024 * 1024;

/** `localStorage`, or null where reaching for it throws -- which it does. */
function storage() {
	try {
		// Not `typeof localStorage`: in a browser with site data blocked the
		// *access* throws, not the lookup.
		return typeof localStorage === 'undefined' ? null : localStorage;
	} catch {
		return null;
	}
}

/** Whether this browser will hold anything at all. */
export function available(store = storage()) {
	if (!store) return false;
	try {
		const probe = `${KEY}.probe`;
		store.setItem(probe, '1');
		store.removeItem(probe);
		return true;
	} catch {
		return false;
	}
}

/**
 * Shares a copy with the other tabs.
 *
 * @param {object} payload from `copySelection`
 * @param {{model?: string}} [meta] what it was copied out of, for the message
 *   the other tab shows
 * @returns {{ok: true, at: number, bytes: number}
 *   | {ok: false, why: string, bytes: number}}
 */
export function put(payload, meta = {}, store = storage()) {
	if (!store) return { ok: false, why: 'this browser is not keeping anything', bytes: 0 };
	const at = Date.now();
	let text;
	try {
		text = JSON.stringify({ at, meta, payload });
	} catch (e) {
		return { ok: false, why: `it would not serialise (${e.message})`, bytes: 0 };
	}
	if (text.length > MOST) {
		// And whatever was shared before goes with it: a stale copy offered to
		// another tab as though it were this one is the one bad outcome here.
		forget(store);
		return { ok: false, why: 'it is too large to share', bytes: text.length };
	}
	try {
		store.setItem(KEY, text);
		return { ok: true, at, bytes: text.length };
	} catch (e) {
		forget(store);
		return { ok: false, why: `the browser refused to store it (${e.name})`, bytes: text.length };
	}
}

/**
 * What another tab last copied, or null.
 *
 * Anything unreadable is nothing: a half-written value, a payload from an
 * older version, a key somebody else's script wrote. A clipboard that throws
 * on paste is worse than one that is empty.
 *
 * @returns {{at: number, meta: object, payload: object}|null}
 */
export function get(store = storage()) {
	if (!store) return null;
	let text;
	try {
		text = store.getItem(KEY);
	} catch {
		return null;
	}
	if (!text) return null;
	try {
		const rec = JSON.parse(text);
		if (!rec || typeof rec !== 'object') return null;
		if (!Number.isFinite(rec.at)) return null;
		const p = rec.payload;
		// The shape `pasteBlocks` needs: something to paste, in the arrays it
		// walks. Checked here so a bad record is nothing rather than a throw
		// three calls later.
		if (!p || typeof p !== 'object') return null;
		if (!Array.isArray(p.blocks) || !Array.isArray(p.parts)) return null;
		if (!p.blocks.length && !p.parts.length) return null;
		return { at: rec.at, meta: rec.meta ?? {}, payload: p };
	} catch {
		return null;
	}
}

/** Takes the shared copy away. The tab's own clipboard is untouched. */
export function forget(store = storage()) {
	try { store?.removeItem(KEY); } catch { /* nothing to do about it */ }
}

/**
 * Calls back when another tab copies something.
 *
 * `storage` fires in every tab of the origin *except* the one that wrote, so
 * this is exactly "somebody else copied" and needs no filtering. It is how a
 * Paste that was greyed out becomes available without the reader reloading.
 *
 * @returns {() => void} stops listening
 */
export function watch(onChange) {
	const listener = (ev) => {
		if (ev.key !== null && ev.key !== KEY) return;
		onChange(get());
	};
	window.addEventListener('storage', listener);
	return () => window.removeEventListener('storage', listener);
}
