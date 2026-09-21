/**
 * Keeping the model across a refresh.
 *
 * Nothing here was saved anywhere. A model is an hour of somebody's work --
 * blocks drawn, equations typed, index lists filled in -- and the page held
 * all of it in one JavaScript object and nowhere else, so a refresh, a crash,
 * a stray Cmd-W or a browser deciding to reclaim a background tab took the
 * lot. Every other editor on a desktop writes something down; this is the
 * browser's version of that.
 *
 * **A draft, not a file.** What is kept is the model as it stood, so the tab
 * can offer it back the next time it opens. It is not a save: it lives in this
 * browser, on this machine, under this origin, and the way to keep a model is
 * still *Save…*, which writes a file the reader can put somewhere and send to
 * somebody. The offer says so.
 *
 * **Why it can decline.** `localStorage` holds a few megabytes -- five is the
 * usual figure, and it is a quota over the whole origin, not per key. The
 * largest assessment here serialises to 35 MB. So this has a ceiling, and a
 * model over it is *not* kept: refusing loudly, with the size said, is the
 * only honest answer, because a draft that is silently not being written is
 * worse than no draft at all. Private windows, cleared site data and browsers
 * with storage switched off behave the same way and are handled the same way:
 * every access is wrapped, and a failure turns the feature off rather than the
 * editor.
 */

/**
 * Where the draft lives. Versioned, so an old shape is ignored rather than read.
 *
 * The name is two products old and stays that way: a storage key is where a
 * reader's unsaved work is, and renaming it to match a title discards that work
 * in every browser holding any -- silently, because the new name finds nothing.
 * See the same note in clipboard.js.
 */
const KEY = 'ecolego.draft.v1';

/**
 * The most a draft may be, serialised.
 *
 * Under the usual 5 MB quota with room to spare: `setItem` throws when the
 * quota is exceeded, and a throw part-way through leaves the old draft gone
 * and the new one not written. Better to decide before writing.
 */
export const MOST = 3 * 1024 * 1024;

/** How long after the last edit the draft is written. */
export const SETTLE = 2000;

/** Whether this browser will hold anything at all. Asked once, and cheaply. */
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

/**
 * Writes the draft, if it fits.
 *
 * @param {object} raw     the model, as it is held
 * @param {object} [meta]  what it is called and where it came from
 * @returns {{ok: true, bytes: number} | {ok: false, why: string, bytes: number}}
 */
export function keep(raw, meta = {}, store = storage()) {
	if (!store) return { ok: false, why: 'this browser is not keeping anything', bytes: 0 };
	let text;
	try {
		text = JSON.stringify({ at: Date.now(), meta, raw });
	} catch (e) {
		return { ok: false, why: `the model would not serialise (${e.message})`, bytes: 0 };
	}
	if (text.length > MOST) {
		// And the old one goes, so a stale draft of a model that has since
		// grown is not offered back as though it were current.
		try { store.removeItem(KEY); } catch { /* nothing to do about it */ }
		return { ok: false, why: 'it is larger than a browser will hold', bytes: text.length };
	}
	try {
		store.setItem(KEY, text);
		return { ok: true, bytes: text.length };
	} catch (e) {
		try { store.removeItem(KEY); } catch { /* nothing to do about it */ }
		return { ok: false, why: `the browser refused to store it (${e.name})`, bytes: text.length };
	}
}

/**
 * The draft, or null.
 *
 * Anything unreadable is treated as nothing: a half-written value, a draft
 * from an older shape of the file, a key somebody else's script wrote.
 */
export function draft(store = storage()) {
	if (!store) return null;
	let text;
	try {
		text = store.getItem(KEY);
	} catch {
		return null;
	}
	if (!text) return null;
	try {
		const held = JSON.parse(text);
		if (!held || typeof held !== 'object' || !held.raw || typeof held.raw !== 'object') {
			return null;
		}
		return { raw: held.raw, meta: held.meta ?? {}, at: Number(held.at) || 0 };
	} catch {
		return null;
	}
}

/** Forgets the draft. */
export function forget(store = storage()) {
	if (!store) return;
	try { store.removeItem(KEY); } catch { /* nothing to do about it */ }
}

/**
 * A writer that waits for the typing to stop.
 *
 * One keystroke is not worth serialising a model for, and a model that takes
 * 40 ms to stringify would make every keystroke cost that. `SETTLE` after the
 * last edit is late enough to be free and early enough to be worth having.
 *
 * `onRefused` is called the first time a model turns out not to fit, and not
 * again until one does -- so the reader is told once that this model is too
 * big to be kept, rather than every two seconds for as long as they work on
 * it.
 */
export function autosaver({ onRefused = null } = {}) {
	let timer = null;
	let said = false;
	let last = null;

	const write = () => {
		timer = null;
		if (!last) return;
		const r = keep(last.raw, last.meta);
		if (r.ok) { said = false; return; }
		if (!said) {
			said = true;
			onRefused?.(r);
		}
	};

	return {
		/** An edit happened; write it when the typing stops. */
		note(raw, meta) {
			last = { raw, meta };
			if (timer) clearTimeout(timer);
			timer = setTimeout(write, SETTLE);
		},
		/** Write it now -- for a tab that is closing. */
		flush() {
			if (timer) { clearTimeout(timer); timer = null; }
			write();
		},
		/** Stop, and forget what was kept: the reader has moved on deliberately. */
		drop() {
			if (timer) { clearTimeout(timer); timer = null; }
			last = null;
			said = false;
			forget();
		},
		get pending() { return timer != null; },
	};
}

/**
 * Whether two models are, as far as this needs to care, the same one.
 *
 * Asked once, on boot: the draft is not worth offering back when it *is* what
 * is already on screen -- opening a file, working on it and refreshing should
 * not be met with an offer to open the same thing again.
 *
 * Cheap first, and the cheap half is the point. A draft is at most `MOST`
 * bytes, but the model beside it may be an assessment that serialises to 35 MB
 * and stringifying that on every boot to answer a question about a 3 MB draft
 * is a second of a cold start for nothing. So: the same collections at the
 * same lengths, and only then the serialisation.
 *
 * Wrong in the direction of offering. An offer that did not need making is one
 * click to dismiss; an offer not made is an hour of work gone.
 */
export function sameModel(a, b) {
	if (!a || !b) return false;
	if ((a.name ?? '') !== (b.name ?? '')) return false;
	const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
	for (const k of keys) {
		const x = a[k];
		const y = b[k];
		if (Array.isArray(x) || Array.isArray(y)) {
			if (!Array.isArray(x) || !Array.isArray(y) || x.length !== y.length) return false;
		}
	}
	try {
		const left = JSON.stringify(a);
		if (left.length > MOST) return false;
		return left === JSON.stringify(b);
	} catch {
		return false;
	}
}

/** "3 minutes ago", for the offer. */
export function howLongAgo(ms, at = Date.now()) {
	const s = Math.max(0, Math.round((at - ms) / 1000));
	if (s < 45) return 'a moment ago';
	const m = Math.round(s / 60);
	if (m < 60) return `${m} minute${m === 1 ? '' : 's'} ago`;
	const h = Math.round(m / 60);
	if (h < 36) return `${h} hour${h === 1 ? '' : 's'} ago`;
	const d = Math.round(h / 24);
	return `${d} day${d === 1 ? '' : 's'} ago`;
}
