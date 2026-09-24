/**
 * How many cores a sampled run is shared over, when the reader says.
 *
 * A probabilistic run, a tornado and a sensitivity design are each a set of
 * independent integrations, and ../worker/prob-pool.js shares them over as
 * many workers as `workersFor` decides: every core the machine reports but
 * one, and fewer where building the model in each would cost more than it
 * saves. This is where a reader says otherwise -- fewer, to keep the machine
 * free for something else, or every one of them, the one auto leaves for the
 * page included. Never more than the machine reports: that is what the list
 * counts up to, and what the worker holds a chosen number to.
 *
 * **Kept per browser, not in the model.** It is a fact about the machine, and
 * the answer does not depend on it: the realisations are the same to the last
 * bit however many cores run them. A model sent to a colleague should not
 * arrive asking for sixteen cores on a laptop that has four.
 */

import { el } from './parts.js';
import { MOST_WORKERS } from '../worker/prob-pool.js';

const KEY = 'kompartment.cores';

/**
 * What this page was last told, so a browser whose storage refuses -- a
 * private window, blocked site data -- still keeps the choice until reload.
 * `undefined` until the stored one has been read.
 */
let held;

/** How many cores the machine reports, or null where the browser does not say. */
export function machineCores() {
	const n = typeof navigator === 'undefined' ? NaN : Number(navigator.hardwareConcurrency);
	return Number.isInteger(n) && n >= 1 ? n : null;
}

/**
 * The most a reader may ask for: the machine's cores. Where the browser does
 * not say how many it has, the cap auto works under stands in for them.
 */
export function mostCores() {
	return machineCores() ?? MOST_WORKERS;
}

const valid = (n) => (Number.isInteger(n) && n >= 1 ? Math.min(n, mostCores()) : null);

/** The reader's number of cores, or null for the tool's own choice. */
export function chosenCores() {
	if (held !== undefined) return held;
	try {
		const stored = localStorage.getItem(KEY);
		held = stored == null ? null : valid(Number(stored));
	} catch {
		held = null;
	}
	return held;
}

/** Remembers `n` cores, or the tool's own choice for null. */
export function chooseCores(n) {
	held = valid(n);
	try {
		if (held == null) localStorage.removeItem(KEY);
		else localStorage.setItem(KEY, String(held));
	} catch {
		// Not stored, which a private window refuses: `held` keeps it for
		// this page, which is as long as such a window keeps anything.
	}
}

/**
 * The row a dialog shows: *auto*, saying what that comes to, then 1 to the
 * machine's cores.
 *
 * @param {object} o
 * @param {number} o.auto        how many cores auto would use for this run
 * @param {number|null} o.value  the choice, or null for auto
 * @param {(n: number|null) => void} o.onChange
 */
export function coresRow({ auto, value, onChange }) {
	const machine = machineCores();
	const sel = el('select', { 'aria-label': 'Cores' });
	sel.append(el('option', { value: '', selected: value == null },
		`auto — ${auto} core${auto === 1 ? '' : 's'}`));
	for (let n = 1; n <= mostCores(); n++) {
		sel.append(el('option', { value: String(n), selected: value === n },
			n === machine ? `${n} — every core this machine reports` : String(n)));
	}
	sel.addEventListener('change', () => onChange(sel.value ? Number(sel.value) : null));
	return el('div', { className: 'pdf-row' },
		el('label', {
			title: 'How many cores the runs are shared over, each running its own copy of '
				+ 'the model. Auto uses every core '
				+ (machine ? `this machine reports (${machine}) ` : 'the machine reports ')
				+ 'but one, which is left for the page, and fewer where building the '
				+ 'model on each would cost more than it saves. A number is used as it '
				+ 'stands, up to every core the machine has. The results are the same to '
				+ 'the last digit either way; this is remembered in this browser, not in '
				+ 'the model.',
		}, 'Cores'),
		sel);
}

/**
 * What the footer says about a pool while it runs: `7 cores`, and in the
 * tooltip why it is that many when that is not what was asked for.
 *
 * @param {{workers: number, asked: number|null, why: string|null}|null} pool
 * @returns {{text: string, title: string}}
 */
export function poolNote(pool) {
	if (!pool) return { text: '', title: '' };
	const n = pool.workers;
	const text = `${n} core${n === 1 ? '' : 's'}`;
	const why = {
		auto: 'the tool’s own choice: every core the machine reports but one, and '
			+ 'fewer where building the model on each would cost more than it saves',
		nesting: 'this browser will not let the simulation start workers of its own, '
			+ 'so the runs are done one after another',
		address: 'the address asks for one (?workers=1)',
		work: 'no more than there are runs to share out',
		cap: machineCores() ? `no more than the ${machineCores()} cores this machine has`
			: `${MOST_WORKERS} at most`,
	}[pool.why] ?? null;
	const asked = pool.asked == null || pool.asked === n ? ''
		: n === 1 ? `, not the ${pool.asked} asked for` : ` of the ${pool.asked} asked for`;
	return {
		text,
		title: `${n === 1 ? 'The runs are done on one core' : `The runs are shared over ${text}`}`
			+ `${asked}${why ? ` — ${why}` : ''}.`,
	};
}
