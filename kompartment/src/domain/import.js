/**
 * Taking blocks out of one model and into another.
 *
 * Ecolego has no such thing: a project is opened or it is not, and a block
 * that exists in one model is retyped into the next. The nearest it comes is
 * the library of assessment templates, which are whole models.
 *
 * The mechanics are already here, in `copySelection` and `pasteBlocks` -- the
 * clipboard carries blocks between two models today. What that route cannot do
 * is the part that makes cross-model work hard: the *dimensions*. A copy
 * carries no index lists of its own, so pasting a per-nuclide block into a
 * model with no nuclide list drops the dimension and every value under it, and
 * pasting one whose list has nuclides the receiving model has never heard of
 * drops those values. Both are the right thing for a clipboard, which has to
 * do something sensible in one step and cannot ask. An import can ask.
 *
 * So this is the asking half. `surveyImport` works out everything that would
 * have to be decided -- which lists are missing, which indices are, what it
 * costs to leave them out, what names collide -- without touching either
 * model; `applyImport` carries out the answers and then hands the ordinary
 * paste the job it is already good at.
 *
 * Two rules run through the defaults, both of them conservative about the
 * model being imported *into*:
 *
 *   A dimension the receiving model does not have is added, because dropping
 *   it collapses the block's whole grid onto one value.
 *
 *   A dimension it does have is used as it stands, because widening one is not
 *   a change to the blocks arriving -- it is a change to every block already
 *   indexed by it, and to the size of the state vector. The values that cannot
 *   be kept are counted and offered, rather than being added behind the back
 *   of a model that did not ask for eight more nuclides.
 */

import * as ed from './edit.js';
import {
	qualifiedName, systemOf, isWithin, parentOf, qualify,
} from './systems.js';

/** Thrown when an import cannot be carried out as asked. */
export class ImportError extends Error {
	constructor(message) {
		super(message);
		this.name = 'ImportError';
	}
}

/** The lists that are worked out from the model rather than written down. */
const isDerived = (list) => !!(list?.derived || list?.auto);

/**
 * A model as the import will find it.
 *
 * A file can carry its radionuclides as `nuclides: [...]` with no index list
 * saying so; the editor makes that explicit as a model is opened, but this can
 * be handed a file that has not been through it. Left alone, a shorthand model
 * looks like one with no radionuclide dimension at all -- so the survey would
 * offer to add one, and the model would end up with two: the list that was
 * added and the shorthand its own blocks are still written against.
 *
 * Only copied when there is something to make explicit, which is why this is
 * not simply done to both models on the way in: the survey runs again on every
 * tick of a checkbox, and cloning an 8 MB model for each of them is not free.
 */
function asFound(project) {
	if (!project?.nuclides?.length) return project;
	if (ed.materialList(project)) return project;
	const copy = structuredClone(project);
	ed.materialiseShorthand(copy);
	return copy;
}

/**
 * Every block the chosen names stand for.
 *
 * A ticked sub-system stands for everything inside it, at every depth, which
 * is what ticking one means and what `copySelection` will carry.
 */
export function blocksChosen(source, names) {
	const paths = ed.systems(source);
	const chosenSystems = names.filter((n) => paths.includes(n));
	const out = new Set(names.filter((n) => !paths.includes(n) && ed.findBlock(source, n)));
	for (const b of ed.allBlocks(source)) {
		const home = systemOf(b);
		if (chosenSystems.some((p) => isWithin(home, p))) out.add(qualifiedName(b));
	}
	return [...out];
}

/**
 * What each block reads, by name.
 *
 * Kept per source model rather than worked out again for every tick of a
 * checkbox: `influences` tokenizes every equation in the model, which on the
 * 3,789-block files this tool reads is a tenth of a second -- once is nothing,
 * once per keystroke is a dialog that lags. The model a dialog is choosing
 * from is never edited while it is being chosen from, so identity is a safe
 * key, and a weak one so that closing the dialog lets the model go.
 */
const GRAPHS = new WeakMap();

function dependencyGraph(source) {
	const cached = GRAPHS.get(source);
	if (cached) return cached;
	const deps = new Map();
	for (const { from, to } of ed.influences(source)) {
		if (!deps.has(to)) deps.set(to, []);
		deps.get(to).push(from);
	}
	GRAPHS.set(source, deps);
	return deps;
}

/**
 * What the chosen blocks cannot arrive without.
 *
 * An expression that reads a parameter is half a block on its own, and the
 * half that is missing is not obvious from the diagram -- the reference is
 * inside the equation. Across models this matters much more than it does for a
 * paste within one: a name left dangling in the model it was copied from still
 * meant something there, and in a different model it means nothing at all.
 *
 * Follows `influences`, which is the model's own reference graph, and the two
 * ends of any connection chosen -- a transfer with one end left behind cannot
 * be pasted anywhere.
 *
 * @returns {string[]} the extra names, in the order they were reached.
 */
export function neededBy(source, names) {
	const have = new Set(blocksChosen(source, names));
	const deps = dependencyGraph(source);
	const extra = [];
	const seen = new Set(have);
	const queue = [...have];
	while (queue.length) {
		const name = queue.shift();
		const found = ed.findBlock(source, name);
		const ends = found && (found.kind === 'transfer' || found.kind === 'inflow')
			? [found.block.from, found.block.to].filter(Boolean)
			: [];
		for (const next of [...(deps.get(name) ?? []), ...ends]) {
			if (seen.has(next) || !ed.findBlock(source, next)) continue;
			seen.add(next);
			extra.push(next);
			queue.push(next);
		}
	}
	return extra;
}

/**
 * Which index lists a set of blocks is written in terms of.
 *
 * Both ways a block can name one: the dimensions it declares, and the keys of
 * the values it holds per index -- a hand-written file can carry an entry for
 * a dimension the block no longer declares, and dropping that silently would
 * lose the value it holds.
 */
function listsUsed(source, names) {
	const used = new Map();
	const note = (list, index) => {
		if (!list) return;
		if (!used.has(list)) used.set(list, new Set());
		if (index != null) used.get(list).add(index);
	};
	for (const name of names) {
		const found = ed.findBlock(source, name);
		if (!found) continue;
		for (const d of found.block.index_lists ?? []) note(d, null);
		for (const e of found.block.entries ?? []) {
			for (const [list, index] of Object.entries(e.index ?? {})) note(list, index);
		}
	}
	// A list defined from another brings that other one with it, however
	// deeply: a sub-set of a sub-set is two lists, not one.
	const all = ed.indexLists(source);
	const byName = new Map(all.map((l) => [l.name, l]));
	const queue = [...used.keys()];
	while (queue.length) {
		const l = byName.get(queue.shift());
		for (const parent of [l?.sub_set_of, l?.mapping?.to]) {
			if (!parent || used.has(parent)) continue;
			used.set(parent, new Set());
			queue.push(parent);
		}
	}
	return used;
}

/**
 * How many blocks of the receiving model a list taken from a derived dimension
 * would leave unnamed. Zero for every other kind of list.
 */
function uncoveredBy(target, targetLists, incoming) {
	const backing = incoming?.sub_set_of ?? incoming?.mapping?.to;
	const list = backing ? targetLists.get(backing) : null;
	if (!list?.auto) return 0;
	return (target[list.auto] ?? []).length;
}

/** How many lists a list is defined through: a root is 0, a sub-set of one is 1. */
function listDepth(byName, name, guard = 0) {
	const list = byName.get(name);
	const parent = list?.sub_set_of ?? list?.mapping?.to;
	if (!parent || guard > 8) return 0;
	return 1 + listDepth(byName, parent, guard + 1);
}

/** How many of a block's values are keyed by one of these indices. */
function valuesUnder(source, names, list, indices) {
	if (!indices.size) return 0;
	let n = 0;
	for (const name of names) {
		const found = ed.findBlock(source, name);
		for (const e of found?.block.entries ?? []) {
			if (indices.has(e.index?.[list])) n++;
		}
	}
	return n;
}

/**
 * What importing these blocks would mean, before anything is done about it.
 *
 * Nothing here writes to either model: this is the report the dialog is built
 * from, and `applyImport` is given it back with the answers filled in.
 *
 * @param {object} target the model being imported into
 * @param {object} source the model the blocks come from
 * @param {string[]} names blocks and sub-systems chosen in the source
 * @param {{bringNeeded?: boolean}} [opts]
 */
export function surveyImport(target, source, names, { bringNeeded = true } = {}) {
	const chosen = blocksChosen(source, names);
	// The sub-systems keep their identity: a ticked one is carried as a
	// sub-system rather than as a heap of the blocks that were in it.
	const paths = ed.systems(source);
	const ticked = names.filter((n) => paths.includes(n));
	const needed = [];
	let take = [...ticked, ...chosen];
	let payload = null;
	let problem = null;

	// Round and round until nothing new arrives. One pass is not enough, and
	// the reason is the connections: a copy carries the transfers between the
	// blocks chosen without being asked, and a transfer has a *rate*, which
	// reads blocks of its own. Importing one compartment out of one small vault model
	// brings the two inflows into it, whose rates read `NearField.Q` and
	// `NearField.Qeq` -- neither of which was chosen, neither of which anything
	// chosen mentions, and without which the model that arrives does not run.
	// Each pass can pull in blocks whose connections pull in more.
	for (let pass = 0; pass < 8; pass++) {
		try {
			payload = take.length ? ed.copySelection(source, take) : null;
		} catch (e) {
			problem = e.message;
			break;
		}
		if (!bringNeeded || !payload) break;
		const coming = payload.blocks.map((b) => b.name);
		const more = neededBy(source, [...ticked, ...coming]);
		if (!more.length) break;
		needed.push(...more);
		take = [...take, ...more];
	}
	const all = [...chosen, ...needed];
	// What a copy actually carries: the blocks above plus the connections
	// between them, which come along without being asked for.
	const coming = payload ? payload.blocks.map((b) => b.name) : [];
	const carried = coming.filter((n) => !all.includes(n));

	// The dimensions of both models as the import will find them, which for a
	// file written in the `nuclides:` shorthand is not what it says.
	const targetLists = ed.indexLists(asFound(target));
	const byName = new Map(targetLists.map((l) => [l.name, l]));
	const sourceLists = new Map(ed.indexLists(asFound(source)).map((l) => [l.name, l]));
	// The receiving model's two material dimensions, so that an incoming one
	// can be offered the matching one by role rather than by name: a donor's
	// catalogue belongs on this model's catalogue and its radionuclides on the
	// radionuclides, whatever either is called.
	const material = targetLists.find((l) => l.for_contaminants) ?? null;
	const nuclides = targetLists.find((l) => l.for_nuclides) ?? material;
	const sameRole = (l) => (l?.for_nuclides ? nuclides : l?.for_contaminants ? material : null);

	const lists = [];
	for (const [name, indices] of listsUsed(source, coming)) {
		const incoming = sourceLists.get(name) ?? null;
		const here = byName.get(name) ?? null;
		// A dimension the receiving model works out for itself -- one index
		// per compartment, per transfer, per element. There is nothing to add
		// and nothing to choose: it will hold this model's blocks.
		if (isDerived(incoming) || isDerived(here)) {
			lists.push({
				name, incoming, status: 'derived', options: [], missing: [], lost: 0,
			});
			continue;
		}
		const asked = [...indices];
		const fits = (list) => {
			const have = new Set((list?.indices ?? []).map((i) => i.name));
			return asked.filter((i) => !have.has(i));
		};
		// Every list in the receiving model this dimension could become,
		// except the ones it works out for itself -- those hold its own blocks
		// and cannot be pointed at. Everything else is offered, including the
		// radionuclide dimension: the files this reads do not agree on how the
		// radionuclides are spelled (one small vault model calls the flagged list
		// `Radionuclides` and keeps a wider `Materials` beside it), so a rule
		// about which dimension may become which would refuse the one mapping
		// somebody actually needs. What each costs is on the row instead.
		const candidates = targetLists.filter((l) => !isDerived(l));
		const row = {
			name,
			incoming,
			// Everything the incoming blocks hold under this dimension, which
			// is what dropping it costs.
			values: valuesUnder(source, coming, name, new Set(asked)),
			// `missing` and `lost` are about the list it is going to use, so
			// they are filled in per candidate and again for the default.
			candidates: candidates.map((l) => ({
				name: l.name,
				missing: fits(l),
				lost: valuesUnder(source, coming, name, new Set(fits(l))),
				// Blocks, not `indexListUsers`, which counts the lists defined
				// from this one as well -- and the element dimension is one of
				// those, so every radionuclide list would report one user it
				// does not have.
				users: ed.allBlocks(target)
					.filter((b) => (b.index_lists ?? []).includes(l.name)).length,
				// Said on the option, because pointing a dimension at this one
				// is what decides whether the values arriving decay.
				material: !!(l.for_contaminants || l.for_nuclides),
			})),
			status: here ? 'present' : 'missing',
			// The material list is the one case where a name that does not
			// match is still obviously the same dimension, so it is offered
			// even when the names differ.
			suggest: here?.name ?? sameRole(incoming)?.name ?? null,
			asked,
			// A list taken from one of the derived dimensions is a list of
			// *blocks*, and the receiving model has blocks of its own that it
			// will not name. That is not a problem in the file it came from --
			// there it named them all -- and it is not one this can fix: which
			// of the receiving model's compartments belong in `Parts` is a
			// modelling decision. But a build refuses over it wherever
			// something reads across the two, so it is said before the import
			// rather than found afterwards.
			uncovered: uncoveredBy(target, byName, incoming),
		};
		lists.push(row);
	}

	// The names that are already taken where the blocks would land, worked out
	// the way `pasteBlocks` works them out so the preview says what will
	// actually happen rather than only that something will.
	const taken = new Set(ed.blockNames(target));
	const clashes = [];
	for (const item of payload?.blocks ?? []) {
		// A block inside a sub-system that is being carried lands inside the
		// copy of that sub-system, which is new and therefore empty.
		if (item.part >= 0) continue;
		const home = item.block.system ?? '';
		if (!taken.has(qualify(home, item.block.name))) {
			taken.add(qualify(home, item.block.name));
			continue;
		}
		let local = item.block.name;
		for (let i = 1; taken.has(qualify(home, local)); i++) local = `${item.block.name}${i}`;
		taken.add(qualify(home, local));
		clashes.push([item.name, qualify(home, local)]);
	}

	return {
		chosen,
		needed,
		carried,
		take,
		payload,
		problem,
		// A list that another is defined from is dealt with first, so that a
		// sub-set being added finds the list it is a sub-set of already there.
		lists: lists.sort((a, b) => listDepth(sourceLists, a.name) - listDepth(sourceLists, b.name)),
		clashes,
		stranded: payload?.stranded ?? [],
		count: coming.length,
	};
}

/**
 * The answers a survey is given when nobody has said otherwise.
 *
 * @returns {Object<string, {mode: string, into: string|null, widen: boolean}>}
 */
export function defaultChoices(survey) {
	const out = {};
	for (const row of survey.lists) {
		if (row.status === 'derived') continue;
		const into = row.suggest;
		out[row.name] = into
			? { mode: 'use', into, widen: false }
			: { mode: 'add', into: null, widen: false };
	}
	return out;
}

/** What one choice costs: the values that will not survive it. */
export function costOf(row, choice) {
	if (row.status === 'derived') return { missing: [], lost: 0 };
	if (choice?.mode === 'drop') {
		return { missing: row.asked, lost: row.values, dimension: true };
	}
	if (choice?.mode !== 'use') return { missing: [], lost: 0 };
	const c = row.candidates.find((x) => x.name === choice.into);
	if (!c) return { missing: [], lost: 0 };
	return choice.widen ? { missing: [], lost: 0, adding: c.missing } : c;
}

/**
 * Carries out an import.
 *
 * The source is copied first and worked on there: a dimension that is going to
 * become one of the receiving model's is *renamed* in that copy, which makes
 * every block, every entry key and every list defined from it follow -- the
 * same rewrite the editor does when a list is renamed by hand, rather than a
 * second one written here to do the same thing slightly differently.
 *
 * @returns a report: what `pasteBlocks` returned, plus what was done to make
 *   the dimensions fit.
 */
export function applyImport(target, source, survey, choices, { into = null } = {}) {
	if (!survey?.payload) throw new ImportError(survey?.problem ?? 'Nothing to import');

	// Both models in the shape every other function here expects, which for a
	// file written in the `nuclides:` shorthand means writing that dimension
	// down. The target is normalised in place because this is the function
	// that edits it, and the editor would have done it on the way in anyway.
	ed.materialiseShorthand(target);
	const work = structuredClone(source);
	ed.materialiseShorthand(work);
	const listsAdded = [];
	const indicesAdded = [];
	const renamedLists = [];
	const dimensionsDropped = [];

	// Two dimensions cannot become the same one: the second rename would find
	// the name taken, and the blocks under it would quietly join the wrong
	// axis. Caught here rather than half way through.
	const seen = new Map();
	for (const [name, choice] of Object.entries(choices ?? {})) {
		if (choice?.mode !== 'use') continue;
		if (seen.has(choice.into)) {
			throw new ImportError(
				`'${seen.get(choice.into)}' and '${name}' would both become `
				+ `'${choice.into}'. One index list can only stand for one.`,
			);
		}
		seen.set(choice.into, name);
	}

	// --- the source copy: dimensions renamed to what they are becoming -----
	for (const row of survey.lists) {
		const choice = choices?.[row.name];
		if (row.status === 'derived' || !choice) continue;
		if (choice.mode === 'use' && choice.into !== row.name) {
			const list = ed.findIndexList(work, row.name);
			if (!list) continue;
			// `renameIndexList` refuses to rename either of the two material
			// dimensions, because the panels of the model they belong to are
			// written in terms of those names. This one is a scratch copy
			// whose only purpose is to be read from, so the guard is lifted.
			const roles = ['for_contaminants', 'for_nuclides'].filter((k) => list[k]);
			for (const k of roles) delete list[k];
			ed.renameIndexList(work, row.name, choice.into);
			const moved = ed.findIndexList(work, choice.into);
			for (const k of roles) moved[k] = true;
			renamedLists.push([row.name, choice.into]);
		}
	}

	// Which of the source's dimensions are lists of its own *blocks*: a list
	// taken from one of those is a list of names that mean nothing until the
	// blocks they name are here. See `fitToDerived`.
	const fromDerived = new Set(
		ed.indexLists(asFound(source)).filter(isDerived).map((l) => l.name),
	);

	// --- the receiving model: the dimensions that have to be there ---------
	for (const row of survey.lists) {
		const choice = choices?.[row.name];
		if (row.status === 'derived' || !choice) continue;

		if (choice.mode === 'drop') {
			dimensionsDropped.push(row.name);
			continue;
		}

		if (choice.mode === 'add') {
			if (ed.findIndexList(target, row.name)) {
				throw new ImportError(
					`An index list named '${row.name}' is already in this model.`,
				);
			}
			const src = row.incoming ?? { name: row.name, indices: [] };
			const made = ed.addIndexList(target, {
				name: row.name,
				indices: (src.indices ?? []).map((i) => ({ ...i })),
			});
			// What the list *is*, beyond its indices: a sub-set or a mapping
			// of another, and whether it is the radionuclide dimension. Each
			// only if what it needs came too -- a sub-set whose parent was
			// dropped is a list that cannot be resolved, and a second
			// radionuclide dimension is not a thing a model can have.
			const parentOfList = src.sub_set_of ?? src.mapping?.to ?? null;
			const parentHere = parentOfList
				? (choices[parentOfList]?.mode === 'drop' ? null
					: choices[parentOfList]?.into ?? parentOfList)
				: null;
			// Not asked whether the parent is there *yet*: one of the derived
			// dimensions comes into existence with the blocks that are about
			// to arrive, so a sub-set of `Transfers` added into a model with
			// no transfers has a parent by the time the paste is done.
			// `fitToDerived` looks again afterwards and takes the relation
			// away if it still has nothing to point at.
			if (src.sub_set_of && parentHere) made.sub_set_of = parentHere;
			if (src.mapping && parentHere) {
				made.mapping = {
					to: parentHere, pairs: (src.mapping.pairs ?? []).map((p) => ({ ...p })),
				};
			}
			if (src.for_nuclides && !ed.indexLists(target).some((l) => l.for_nuclides)) {
				made.for_nuclides = true;
			}
			if (src.for_contaminants && !ed.materialList(target)) {
				made.for_contaminants = true;
			}
			if (made.for_contaminants || made.for_nuclides) {
				carryNuclides(target, source, made.indices.map((i) => i.name));
				// `nuclides` is the shorthand the rest of the model is read
				// through; a list that has just become the radionuclide
				// dimension has to be in it.
				ed.syncNuclidesFromMaterialList(target);
			}
			if (src.comment) made.comment = src.comment;
			listsAdded.push({
				name: row.name,
				indices: made.indices.length,
				// Whether its indices are block names -- which is what makes
				// it need reading again once the blocks have landed.
				blockBacked: !!parentOfList && fromDerived.has(parentOfList),
			});
			continue;
		}

		// Using one that is already here, and perhaps widening it.
		const list = ed.findIndexList(target, choice.into);
		if (!list) throw new ImportError(`No index list named '${choice.into}'`);
		if (!choice.widen) continue;
		const have = new Set(list.indices.map((i) => i.name));
		const adding = row.asked.filter((i) => !have.has(i));
		// Before the indices, not after: `addIndex` gives a nuclide the table
		// has never heard of a half-life of "stable" so that the model still
		// runs, and a donor that knew better has to have said so first -- an
		// override that is already there is left alone.
		if (list.for_contaminants || list.for_nuclides) carryNuclides(target, source, adding);
		for (const index of adding) ed.addIndex(target, choice.into, index);
		if (adding.length) indicesAdded.push({ list: choice.into, indices: adding });
	}

	// --- and now the ordinary paste ----------------------------------------
	const payload = ed.copySelection(work, survey.take);
	// Always to a clear spot. A paste inside one model keeps the coordinates
	// it was copied from, nudged, because that is where the copy belongs; an
	// import arrives in a diagram that knows nothing about it, and landing on
	// top of whatever was drawn there reads as a fault rather than as an
	// import.
	const at = ed.freeSpotIn(target, into ?? (payload.system ?? ''));
	const report = ed.pasteBlocks(target, payload, { system: into, at });

	// Last, because it needs to know what the blocks are called now: a list
	// taken from one of the derived dimensions is a list of *block names*.
	const { narrowed, emptied } = fitToDerived(target, listsAdded, report.renamed);
	for (const name of emptied) {
		const at2 = listsAdded.findIndex((l) => l.name === name);
		if (at2 >= 0) listsAdded.splice(at2, 1);
		dimensionsDropped.push(name);
	}

	return {
		...report,
		listsAdded,
		indicesAdded,
		renamedLists,
		dimensionsDropped,
		narrowed,
		// What the paste had to drop after all of that -- which is what the
		// choices asked for, and is worth saying again in those terms.
		lostEntries: report.lostEntries,
	};
}

/**
 * Cuts an added list down to the blocks that actually arrived.
 *
 * A list taken from one of the derived dimensions is a list of *block names*:
 * `AdvectiveTransfers` in one small vault model is a sub-set of `Transfers` naming
 * seventeen of them, and `Media` is a mapping onto `Compartments`. Added to
 * another model as they stand, they name blocks that model has never had --
 * which is not a warning, it is a model that will not build.
 *
 * So they are re-read against what is now here, under the names things now
 * have. What survives is what came; what does not is gone, and a list with
 * nothing left is not a dimension at all -- the blocks that were indexed by it
 * lose it, which is what they would have had if it had been dropped on the way
 * in, and the caller says so.
 */
function fitToDerived(target, added, renamed) {
	const map = new Map(renamed ?? []);
	const known = new Set(ed.blockNames(target));
	const here = (n) => known.has(map.get(n) ?? n);
	const now = (n) => map.get(n) ?? n;
	const narrowed = [];
	const emptied = [];

	for (const { name, blockBacked } of added) {
		const list = ed.findIndexList(target, name);
		if (!list) continue;
		const parentName = list.sub_set_of ?? list.mapping?.to;
		if (!parentName) continue;
		const parent = ed.findIndexList(target, parentName);
		if (!parent) {
			// It was taken from a list that is not here after all -- dropped
			// on the way in, or a derived one that never came into existence
			// because no block of that kind arrived. A relation pointing at
			// nothing is worse than none: it is a list that cannot resolve.
			delete list.sub_set_of;
			delete list.mapping;
			// And if what it held were block names, none of them names a block
			// here: what is left is a dimension of strings that mean nothing,
			// which is worse than not having the dimension at all.
			if (blockBacked) list.indices = [];
			else continue;
		} else if (!(parent.derived || parent.auto)) continue;

		const was = list.indices.length;
		if (list.sub_set_of) {
			list.indices = list.indices
				.filter((i) => here(i.name))
				.map((i) => ({ ...i, name: now(i.name) }));
		}
		if (list.mapping) {
			// `to` is the parent's index, which here is the block.
			list.mapping.pairs = (list.mapping.pairs ?? [])
				.filter((p) => here(p.to))
				.map((p) => ({ ...p, to: now(p.to) }));
			const used = new Set(list.mapping.pairs.map((p) => p.from));
			list.indices = list.indices.filter((i) => used.has(i.name));
		}
		// The values keyed by those indices are block names as well, and the
		// paste does not re-spell them: it re-spells the keys of the derived
		// dimensions themselves, and this is a list *taken from* one. So they
		// follow the renames here, and whatever names an index that did not
		// survive goes with it.
		const keep = new Set(list.indices.map((i) => i.name));
		for (const kind of ed.KINDS) {
			for (const b of target[kind] ?? []) {
				if (!Array.isArray(b.entries)) continue;
				for (const e of b.entries) {
					const was = e.index?.[name];
					if (was != null && now(was) !== was) e.index[name] = now(was);
				}
				b.entries = b.entries
					.filter((e) => e.index?.[name] == null || keep.has(e.index[name]));
			}
		}

		if (!list.indices.length) {
			emptied.push(name);
			for (const b of ed.allBlocks(target)) {
				const dims = b.index_lists ?? [];
				if (!dims.includes(name)) continue;
				ed.setBlockDimensions(target, ed.qualifiedName(b), dims.filter((d) => d !== name));
			}
			const at = (target.index_lists ?? []).indexOf(list);
			if (at >= 0) target.index_lists.splice(at, 1);
		} else if (list.indices.length !== was) {
			narrowed.push({ list: name, kept: list.indices.length, was });
		}
	}
	return { narrowed, emptied };
}

/**
 * Brings a nuclide's decay data along with the nuclide.
 *
 * ICRP 107 is the default for both the half-life and the chains, so most
 * nuclides need nothing: they are in the table and both models already agree
 * about them. What has to be carried is what the source model said *instead* --
 * `addIndex` gives a name the table has never heard of a half-life of "stable"
 * so the model still runs, and a source that knew better must win over that.
 */
function carryNuclides(target, source, nuclides) {
	for (const n of nuclides) {
		if (!ed.hasHalfLifeOverride(source, n)) continue;
		if (ed.hasHalfLifeOverride(target, n)) continue;
		ed.setHalfLife(target, n, source.half_lives[n]);
	}
}

/**
 * What is worth saying about the nuclides an import would bring.
 *
 * Kept apart from the survey's list rows because it is about the indices
 * rather than about the dimension: two models can agree perfectly on what
 * `Nuclide` is and still disagree about how long Ra-226 lasts.
 */
export function nuclideNotes(target, source, survey, choices) {
	const row = survey.lists.find((l) => l.incoming?.for_nuclides)
		?? survey.lists.find((l) => l.incoming?.for_contaminants);
	if (!row) return null;
	const choice = choices?.[row.name];
	const cost = costOf(row, choice);
	const adding = choice?.mode === 'add'
		? row.incoming.indices.map((i) => i.name)
		: (cost.adding ?? []);
	const conflicts = [];
	const unknown = [];
	for (const n of adding) {
		const theirs = ed.halfLifeOf(source, n);
		const ours = ed.halfLifeOf(target, n);
		if (ours != null && theirs != null && ours !== theirs) {
			conflicts.push({ nuclide: n, source: theirs, target: ours });
		}
		if (theirs == null && ours == null) unknown.push(n);
	}
	return {
		adding,
		conflicts,
		unknown,
		// A model that has written its chains down has stopped following its
		// nuclide list, so a nuclide added to it arrives with no ingrowth
		// until somebody says what it decays into.
		chainsPinned: !!target.chains && adding.length > 0,
	};
}

/** Where an import may be put, for the picker that asks. */
export function destinations(target) {
	return ['', ...ed.systems(target)];
}

/** The sub-system a name would land in, for the preview. */
export function landsIn(into, block) {
	return into == null ? (block.system ?? '') : into;
}

export { parentOf, qualifiedName };
