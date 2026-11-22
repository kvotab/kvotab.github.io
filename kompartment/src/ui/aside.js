/**
 * Models put aside when another took their place.
 *
 * New, an example picked from the list at the top, a file opened or dropped,
 * a draft restored: each replaces the model in the tab, and undo does not
 * reach back across a replaced model -- the thing it would put back is not on
 * screen to be looked at first. So a slip on the example list took an
 * afternoon's unsaved work with it, and the tab's draft went the same way two
 * seconds later, written over by the model that replaced it.
 *
 * Now the model being replaced is put aside first, when it is worth keeping:
 * one that has been edited since it was opened, or one that came from
 * anywhere but the example list or New as they come -- those are one choice
 * away, and a list of five filled with them would push out the ones that are
 * not. The line above the tabs names it and brings it back, which puts the
 * model it replaces aside in its turn; and the list at the top keeps the last
 * five between visits, under a heading of their own.
 *
 * **Where they are kept.** In this tab, always; and in the browser's own
 * database (IndexedDB) for the next visit, which holds far more than the five
 * megabytes the draft has to fit into -- a 35 MB assessment is kept as easily
 * as a test model. Every access is wrapped: a private window, storage switched
 * off or a quota reached leaves the list in this tab only, and the editor
 * working.
 *
 * Nothing is asked first, as nothing was before: the model goes aside and the
 * new one opens, and the way back is one click.
 */

/** How many are kept. */
export const MOST_ASIDE = 5;

/** Past this the model is kept in this tab and not written for the next visit. */
export const MOST_BYTES = 64 * 1024 * 1024;

const DB_NAME = 'kompartment.aside';
const STORE = 'models';

/**
 * Whether the model being replaced is worth putting aside.
 *
 * @param {object} o
 * @param {boolean} o.edited   whether it was changed since it was opened (the
 *   undo history has a step in it: a layout edit counts, which a revision
 *   counter that only numeric edits move would not)
 * @param {object|null} o.source  where it came from: `{example}` for one of
 *   the bundled ones, `{blank: true}` or the label `New model` for New,
 *   `{broughtBack}` or `{restored}` for one put back
 */
export function worthPuttingAside({ edited, source }) {
	if (edited) return true;
	if (!source) return false;
	// One brought back from the list, or a draft restored, is worth keeping
	// again as it is, whatever it was first called: a model begun with New and
	// brought back is not New as it comes.
	if (source.broughtBack || source.restored) return true;
	if (source.example) return false;
	if (source.blank || source.label === 'New model') return false;
	return true;
}

/** An id that sorts by when it was made and is not reused. */
function newId() {
	return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * The list, in this tab and in the browser's database.
 *
 * Synchronous to read -- the list at the top is built from it on every change
 * -- and written through to the database behind, where a failure is nothing
 * worse than a list that lasts the visit.
 *
 * @param {object} [o]
 * @param {IDBFactory|null} [o.idb]  the database, or null for this tab only
 * @param {number} [o.most]
 */
export function asideStore({ idb = globalThis.indexedDB ?? null, most = MOST_ASIDE } = {}) {
	/** Newest first: `{ id, title, label, at, text }`. */
	const entries = [];
	let opening = null;
	// When each was put aside, strictly later than the one before: several in
	// one millisecond still sort in the order they were put aside.
	let lastAt = 0;
	const stamp = () => {
		lastAt = Math.max(Date.now(), lastAt + 0.001);
		return lastAt;
	};

	const database = () => {
		if (opening) return opening;
		opening = new Promise((resolve) => {
			if (!idb) { resolve(null); return; }
			let req;
			try {
				req = idb.open(DB_NAME, 1);
			} catch {
				resolve(null);
				return;
			}
			req.onupgradeneeded = () => {
				try { req.result.createObjectStore(STORE, { keyPath: 'id' }); } catch { /* there already */ }
			};
			req.onsuccess = () => {
				const db = req.result;
				// Another tab upgrading the database, or deleting it, waits
				// for every connection to close: this one closes rather than
				// keep it waiting for as long as this tab is open, and the
				// next write opens it again.
				db.onversionchange = () => {
					try { db.close(); } catch { /* closed already */ }
					opening = null;
				};
				resolve(db);
			};
			req.onerror = () => resolve(null);
			req.onblocked = () => resolve(null);
		});
		return opening;
	};

	/** One transaction; resolves with what `fn` asked for, or null for any failure. */
	const transact = async (mode, fn) => {
		const db = await database();
		if (!db) return null;
		return new Promise((resolve) => {
			let tx;
			let req = null;
			try {
				tx = db.transaction(STORE, mode);
				req = fn(tx.objectStore(STORE));
			} catch {
				resolve(null);
				return;
			}
			tx.oncomplete = () => resolve(req ? req.result : true);
			tx.onerror = () => resolve(null);
			tx.onabort = () => resolve(null);
		});
	};

	const meta = ({ text, ...rest }) => ({ ...rest, bytes: text.length });

	return {
		/**
		 * What earlier visits put aside, joined to what this one already has:
		 * the newest `most` kept, the rest let go from the database too.
		 */
		async load() {
			const stored = await transact('readonly', (s) => s.getAll());
			if (Array.isArray(stored)) {
				for (const e of stored) {
					if (!e || typeof e.text !== 'string' || !e.id) continue;
					if (entries.some((x) => x.id === e.id || x.text === e.text)) continue;
					entries.push({
						id: String(e.id), title: String(e.title ?? ''), label: String(e.label ?? ''),
						at: Number(e.at) || 0, text: e.text,
					});
				}
				entries.sort((a, b) => b.at - a.at);
				for (const e of entries) lastAt = Math.max(lastAt, e.at);
				const gone = entries.splice(most);
				if (gone.length) transact('readwrite', (s) => { for (const g of gone) s.delete(g.id); });
			}
			return entries.map(meta);
		},

		/** Newest first, without the models themselves. */
		list() {
			return entries.map(meta);
		},

		/**
		 * Puts a model aside. The same model put aside again moves to the top
		 * rather than taking a second place, and the oldest past `most` goes.
		 *
		 * @param {{text: string, title: string, label?: string}} m
		 * @returns {object} the entry, without the model
		 */
		put({ text, title, label = '' }) {
			const was = entries.findIndex((e) => e.text === text);
			const old = was >= 0 ? entries.splice(was, 1)[0] : null;
			const entry = { id: newId(), title: String(title ?? ''), label: String(label ?? ''), at: stamp(), text };
			entries.unshift(entry);
			const gone = entries.splice(most);
			transact('readwrite', (s) => {
				if (old) s.delete(old.id);
				for (const g of gone) s.delete(g.id);
				if (text.length <= MOST_BYTES) s.put(entry);
			});
			return meta(entry);
		},

		/** Takes one out of the list, to be brought back: the entry with its model, or null. */
		take(id) {
			const k = entries.findIndex((e) => e.id === id);
			if (k < 0) return null;
			const [entry] = entries.splice(k, 1);
			transact('readwrite', (s) => s.delete(id));
			return entry;
		},

		/** Lets one go. */
		remove(id) {
			const k = entries.findIndex((e) => e.id === id);
			if (k >= 0) entries.splice(k, 1);
			transact('readwrite', (s) => s.delete(id));
		},
	};
}
