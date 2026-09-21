/**
 * Recording that a block has been reviewed, and noticing when that lapses.
 *
 * > "the definition of expressions (equations) and the transcription of
 * > numerical values from the supporting documentation is subject to a review
 * > and approval process. This form of Quality Assurance lies at the heart of
 * > AMBER."
 *
 * Three states -- **approved**, **needs review**, and no status at all -- with
 * a record of who approved what, when, and why. That much is bookkeeping.
 *
 * **The part that is not bookkeeping is when an approval stops counting.** A
 * parameter approved last month is not approved now if somebody has since
 * changed it; and it is not approved now if somebody has changed something it
 * is *worked out from*. The second is the one nobody tracks by hand: approve
 * `Dose = WellConc * intake * doseCoeff`, then halve `intake`, and the dose has
 * been reviewed only in the sense that a number nobody checked used to be
 * right.
 *
 * This tool can answer that properly, because it already knows what reads what
 * -- the same walk the delete guard and the re-solve fingerprint are built on.
 * So an approval records a *stamp* of the block as it stood, and a status is
 * **computed**, never stored:
 *
 *   - the block's own stamp still matches, and
 *   - everything it reads is itself currently approved.
 *
 * Computed rather than invalidated-on-edit for the reason most of this file
 * exists: a status that is written down by one code path and read by another is
 * a status that goes stale the first time an edit takes a path nobody thought
 * of. Nothing here has to be told about an edit.
 *
 * **What it does not do.** It does not stop a parameter being used: an
 * unapproved block runs exactly as an approved one does. AMBER says the same --
 * "the marking of a parameter as having been reviewed ... does not ensure or
 * prohibit the use of the parameter in any calculations". A lock is the one
 * thing that bites, and it bites on editing rather than on running.
 */

import { qualifiedName } from './systems.js';
import { allBlocks, blockIndex } from './blocks.js';
import { referenceGraph, equationsOf } from './queries.js';

/** What a block's QA can be. */
export const QA_STATES = ['approved', 'review', 'none'];

/** What each is called where somebody reads it. */
export const QA_LABEL = {
	approved: 'Approved',
	review: 'Needs review',
	none: 'No QA status',
	stale: 'Approved, but something changed',
};

/**
 * Fields a review is *about*.
 *
 * What a reviewer checked is the definition: the equation, the number, the
 * unit, the distribution, the index lists it is written over. Not where the box
 * sits on the diagram, not its colour, not the comment -- moving a block does
 * not un-review it, and if it did the feature would be too annoying to leave
 * switched on. The same judgement `NOT_NUMERIC` makes in ./fingerprint.js, and
 * for the same reason, but a longer list: a unit is not a number and a review
 * is still about it.
 */
const NOT_REVIEWED = new Set([
	'x', 'y', 'w', 'h', 'shape', 'colour', 'color', 'label', 'collapsed',
	'comment', 'note', 'notes', 'qa',
]);

/**
 * A stamp of the block as it stands: everything a review was about.
 *
 * A string rather than a hash, because it is written into the model file and a
 * reader should be able to see what changed. On a parameter with four hundred
 * indexed entries that is a long string, which is the price of being able to
 * say *what* lapsed rather than only that something did.
 */
export function stamp(block) {
	const keep = {};
	for (const [k, v] of Object.entries(block ?? {})) {
		if (NOT_REVIEWED.has(k)) continue;
		keep[k] = v;
	}
	if (Array.isArray(block?.entries)) {
		keep.entries = block.entries.map((e) => {
			const out = {};
			for (const [k, v] of Object.entries(e ?? {})) if (!NOT_REVIEWED.has(k)) out[k] = v;
			return out;
		});
	}
	return JSON.stringify(keep, Object.keys(keep).sort());
}

/** Whether the QA features are switched on for this model. */
export function enabled(project) {
	return project?.simulation?.qa === true;
}

/** Switches them on or off. Off leaves the records alone, as AMBER's does. */
export function setEnabled(project, on) {
	const sim = project.simulation ?? (project.simulation = {});
	if (on) sim.qa = true; else delete sim.qa;
	return on;
}

/**
 * Records an approval, or a request for review.
 *
 * @param {object} block
 * @param {object} what
 * @param {'approved'|'review'} what.status
 * @param {string} [what.by]        who made the change
 * @param {string} [what.reviewer]  who checked it
 * @param {string} [what.comment]
 * @param {boolean} [what.locked]   refuse edits until it is unlocked
 * @param {string} [what.at]        an ISO date; the caller's clock, not ours
 */
export function record(block, what) {
	const qa = block.qa ?? (block.qa = { history: [] });
	const entry = {
		status: what.status === 'approved' ? 'approved' : 'review',
		by: String(what.by ?? '').trim(),
		reviewer: String(what.reviewer ?? '').trim(),
		comment: String(what.comment ?? '').trim(),
		at: what.at ?? new Date().toISOString(),
	};
	qa.status = entry.status;
	qa.stamp = stamp(block);
	qa.locked = entry.status === 'approved' && !!what.locked;
	qa.history = [...(qa.history ?? []), entry].slice(-50);
	return qa;
}

/** Forgets a block's QA entirely. */
export function clear(block) {
	delete block.qa;
}

/**
 * The status of every block, with the reason where it is not simply approved.
 *
 * Four outcomes, and the two in the middle are the point:
 *
 *   `approved`  reviewed, unchanged since, and everything it reads is too
 *   `stale`     reviewed, but the block itself has changed since
 *   `review`    reviewed, unchanged, but something it depends on is not
 *               approved -- or it was marked as needing review outright
 *   `none`      never reviewed
 *
 * The dependency rule is transitive by construction: a block whose input is
 * `stale` is `review`, and so is anything reading *that*. Resolved by walking
 * the graph to a fixed point, which on the largest model here is a handful of
 * passes over a few thousand names.
 *
 * @returns {Map<string, {state: string, why: string}>}
 */
export function statuses(project, graph = null) {
	const g = graph ?? referenceGraph(project);
	const index = blockIndex(project);
	const out = new Map();

	// First pass: what each block says about itself.
	for (const [q, { block }] of index) {
		const qa = block.qa;
		if (!qa || !qa.status) { out.set(q, { state: 'none', why: '' }); continue; }
		if (qa.status !== 'approved') {
			out.set(q, { state: 'review', why: 'marked as needing review' });
			continue;
		}
		if (qa.stamp !== stamp(block)) {
			out.set(q, { state: 'stale', why: 'it has changed since it was approved' });
			continue;
		}
		out.set(q, { state: 'approved', why: '' });
	}

	// Second: an approval is only as good as what it was worked out from.
	// Repeated until nothing moves, so the rule reaches all the way down.
	for (let pass = 0; pass < index.size + 1; pass++) {
		let moved = false;
		for (const [q, at] of out) {
			if (at.state !== 'approved') continue;
			for (const dep of g.reads.get(q) ?? []) {
				const d = out.get(dep);
				if (!d || d.state === 'approved') continue;
				out.set(q, {
					state: 'review',
					why: `${dep} is ${d.state === 'none' ? 'not reviewed' : 'no longer approved'}`,
				});
				moved = true;
				break;
			}
		}
		if (!moved) break;
	}
	return out;
}

/** How many of each, for the panel that says whether a model has been reviewed. */
export function summary(project, graph = null) {
	const counts = { approved: 0, stale: 0, review: 0, none: 0, locked: 0 };
	const found = statuses(project, graph);
	for (const { state } of found.values()) counts[state] = (counts[state] ?? 0) + 1;
	for (const b of allBlocks(project)) if (b.qa?.locked) counts.locked++;
	counts.total = found.size;
	return counts;
}

/** The blocks a lock is currently holding. */
export function lockedNames(project) {
	return allBlocks(project)
		.filter((b) => b.qa?.locked)
		.map((b) => qualifiedName(b));
}

/**
 * Which locked blocks an edit has changed, comparing two models.
 *
 * The check the editor runs after every edit, because every edit goes through
 * one funnel and this is cheaper and far more reliable than a guard inside each
 * of the fifty functions that can change a block. A lock that could be walked
 * round by one unusual code path is not a lock.
 *
 * A block that has been *deleted* counts as changed: removing something is the
 * most complete way of editing it.
 *
 * @returns {string[]} qualified names
 */
export function brokenLocks(before, after) {
	const was = blockIndex(before);
	const now = blockIndex(after);
	const out = [];
	for (const [q, { block }] of was) {
		if (!block.qa?.locked) continue;
		const then = now.get(q);
		if (!then) { out.push(q); continue; }
		if (stamp(then.block) !== stamp(block)) out.push(q);
	}
	return out;
}

/** Sets or clears a lock, which only an approved block may carry. */
export function setLocked(block, locked) {
	if (!block.qa || block.qa.status !== 'approved') return false;
	block.qa.locked = !!locked;
	return true;
}

/**
 * What a reviewer is looking at: every equation and value the block carries.
 *
 * The thing a review is *of*, gathered in one place so the approval dialog can
 * show it rather than making somebody open the settings, read them, close them
 * and then approve from memory.
 */
export function whatToReview(project, name) {
	const found = blockIndex(project).get(name);
	if (!found) return null;
	const { block, collection, kind } = found;
	return {
		name,
		kind,
		unit: String(block.unit ?? '').trim(),
		equations: equationsOf(block, collection),
		indexLists: [...(block.index_lists ?? [])],
		distributed: !!(block.pdf || (block.entries ?? []).some((e) => e?.pdf)),
		comment: String(block.comment ?? '').trim(),
		qa: block.qa ?? null,
	};
}
