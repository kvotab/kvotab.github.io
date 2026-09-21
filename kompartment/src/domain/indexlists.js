/**
 * N-dimensional index lists.
 *
 * An index list is a named, ordered set of indices -- nuclides, landscape
 * objects, scenarios, age classes. Every block carries an ordered array of
 * index lists, its *dimension*, and holds one value per combination of
 * indices. A compartment indexed by [Nuclide, Landscape] with 5 nuclides and
 * 3 objects is 15 state variables.
 *
 * Three kinds of list:
 *
 *   root     an independent list of indices
 *   sub-set  a selection from a root list; its indices ARE the root's, so a
 *            value indexed by the sub-set is reachable from the root
 *   mapped   a list with an explicit index-to-index mapping onto another list,
 *            used to relate two different dimensions
 *
 * The hard part is not storing the values, it is resolving a
 * reference between blocks of *different* dimension. When a block indexed by
 * [Nuclide, Landscape] mentions one indexed by [Nuclide], the nuclide
 * component has to be carried across and the landscape component dropped. That
 * is what `projection()` computes, and what the code generator turns into
 * offset arithmetic.
 */

import { elementOf } from './nuclides.js';

/** `[0, 1, ... n-1]`, the translation a root list needs to itself. */
function identity(n) {
	const table = new Int32Array(n);
	for (let i = 0; i < n; i++) table[i] = i;
	return table;
}

/** `outer[inner[k]]`, with -1 carried through rather than read as a position. */
function compose(inner, outer) {
	const table = new Int32Array(inner.length).fill(-1);
	for (let k = 0; k < inner.length; k++) {
		const mid = inner[k];
		table[k] = mid < 0 ? -1 : outer[mid];
	}
	return table;
}

export class IndexError extends Error {
	constructor(message, detail) {
		super(message);
		this.name = 'IndexError';
		this.detail = detail ?? null;
	}
}

/**
 * The index-list model for one project, with everything the builder needs
 * precomputed: enabled indices, strides, and index-to-index maps.
 */
export class IndexSpace {
	/**
	 * @param {Array} rawLists project.index_lists
	 */
	constructor(rawLists = []) {
		this.lists = new Map();
		this.order = [];

		for (const raw of rawLists) {
			if (!raw?.name) throw new IndexError('An index list needs a name');
			if (this.lists.has(raw.name)) {
				throw new IndexError(`Duplicate index list '${raw.name}'`);
			}
			const list = {
				name: raw.name,
				for_contaminants: !!raw.for_contaminants,
				// The sub-set of the catalogue that has half-lives. Carried so
				// that a caller holding one of these rather than the raw list
				// can still tell the two material roles apart.
				for_nuclides: !!raw.for_nuclides,
				// Ecolego's scenario dimension: alternative runs rather than a
				// real axis of the model. One index of it is active at a time
				// and every block indexed by it is read at that one, so the
				// dimension is not a dimension of the simulation at all. See
				// `withoutScenarios` below.
				for_scenarios: !!raw.for_scenarios,
				sub_set_of: raw.sub_set_of ?? null,
				mapping: raw.mapping ?? null,
				comment: raw.comment ?? '',
				// Carried through: `listApplies` reads `auto` to decide
				// whether a kind of block may be indexed by this list, and a
				// caller holding one of these objects rather than the raw list
				// got an answer of "anything may" for the two dimensions that
				// are made of the model's own blocks.
				...(raw.auto ? { auto: raw.auto } : {}),
				...(raw.derived ? { derived: true } : {}),
				indices: (raw.indices ?? []).map((i) => (
					typeof i === 'string'
						? { name: i, enabled: true }
						: { name: i.name, enabled: i.enabled !== false }
				)),
			};
			this.lists.set(list.name, list);
			this.order.push(list.name);
		}

		this._resolve();
	}

	/**
	 * The scenario dimension, if the model has one.
	 *
	 * Ecolego marks one root list with `predefined-type = SCENARIOS`. A block
	 * may be indexed by that list, by a sub-set of it, or by a list mapped
	 * onto it, and all three are the same dimension as far as the simulation
	 * is concerned: `ScenarioIndexWrapper.setObject` walks a block's lists
	 * looking for one whose root is the all-scenarios list, and takes the
	 * matching index by name for a sub-set or through the mapping for a mapped
	 * list. This does the same.
	 */
	_placeScenarios() {
		this.scenarioRoot = null;
		for (const name of this.order) {
			const list = this.lists.get(name);
			if (list.for_scenarios && list.rootName === list.name) {
				this.scenarioRoot = list.name;
				break;
			}
		}
		// Flagged on a list that turns out not to be a root: the root of it is
		// the scenario dimension all the same.
		if (!this.scenarioRoot) {
			for (const name of this.order) {
				const list = this.lists.get(name);
				if (list.for_scenarios) { this.scenarioRoot = list.rootName; break; }
			}
		}
		for (const list of this.lists.values()) {
			list.isScenario = !!this.scenarioRoot && list.rootName === this.scenarioRoot;
		}
		// The one that is active. Left at the first, which is what opening a
		// project in Ecolego selects.
		this.scenario = this.scenarios()[0] ?? null;
	}

	/** The scenarios a model offers, by name. */
	scenarios() {
		return this.scenarioRoot ? this.indexNames(this.scenarioRoot) : [];
	}

	/** Whether `name` is the scenario dimension, however it reaches it. */
	isScenarioDim(name) {
		return !!this.lists.get(name)?.isScenario;
	}

	/**
	 * Chooses the active scenario. Anything that is not one of them -- and
	 * `null` -- leaves the model with no scenario selected, which is what a
	 * model without a scenario list has.
	 */
	setScenario(name) {
		const available = this.scenarios();
		this.scenario = name != null && available.includes(name) ? name : null;
		return this.scenario;
	}

	/**
	 * The index of `dim` that stands for the active scenario: the scenario
	 * itself in the root list, the one of the same name in a sub-set, or
	 * whatever the mapping sends it to.
	 */
	scenarioIndexIn(dim) {
		const list = this.lists.get(dim);
		if (!list?.isScenario || this.scenario == null) return null;
		const root = this.lists.get(this.scenarioRoot);
		const rootPos = root.positionOf.get(this.scenario);
		if (rootPos === undefined) return null;
		const pos = list === root ? rootPos : list.down[rootPos];
		return pos >= 0 ? list.enabled[pos].name : null;
	}

	/**
	 * A block's dimensions as the simulation sees them: the scenario is not
	 * one, because only one of its indices is live at a time.
	 *
	 * This is the rule for a scenario’s dimension, which is the
	 * dimension count a generated class is written with.
	 */
	withoutScenarios(dims) {
		if (!this.scenarioRoot) return dims ?? [];
		return (dims ?? []).filter((d) => !this.isScenarioDim(d));
	}

	/**
	 * An index tuple with the active scenario put back in, so that a value
	 * stored per scenario is read at the right one -- `ScenarioIndexWrapper.wrap`.
	 *
	 * @param {string[]} dims  the block's dimensions *as written*
	 * @param {object} tuple   { listName: indexName }, without the scenario
	 */
	pinScenario(dims, tuple) {
		if (!this.scenarioRoot || this.scenario == null) return tuple;
		let out = tuple;
		for (const d of dims ?? []) {
			if (!this.isScenarioDim(d)) continue;
			const name = this.scenarioIndexIn(d);
			if (name == null) continue;
			if (out === tuple) out = { ...tuple };
			out[d] = name;
		}
		return out;
	}

	/** Fills in sub-set membership and validates references between lists. */
	_resolve() {
		for (const list of this.lists.values()) {
			// Enabled indices are the ones that take part in a simulation.
			list.enabled = list.indices.filter((i) => i.enabled);
			list.size = list.enabled.length;
			list.positionOf = new Map(list.enabled.map((i, k) => [i.name, k]));
			// Every index it holds, switched on or not. Membership in a root
			// list is about what the list *contains*; being switched on is a
			// separate question, and conflating the two is what made turning
			// a nuclide off refuse to load the model.
			list.names = new Set(list.indices.map((i) => i.name));
		}

		for (const list of this.lists.values()) {
			if (list.sub_set_of) {
				const root = this.lists.get(list.sub_set_of);
				if (!root) {
					throw new IndexError(
						`Index list '${list.name}' is a sub-set of '${list.sub_set_of}', ` +
						`which does not exist`, list.name,
					);
				}
				if (root.sub_set_of) {
					throw new IndexError(
						`'${list.name}' is a sub-set of '${root.name}', which is itself a ` +
						`sub-set. Sub-sets must be taken from a root list.`, list.name,
					);
				}
				for (const idx of list.enabled) {
					if (!root.names.has(idx.name)) {
						throw new IndexError(
							`'${idx.name}' is in the sub-set '${list.name}' but not in its ` +
							`root list '${root.name}'`, list.name,
						);
					}
				}
				// An index switched off in the root is out of the simulation,
				// and a sub-set of it cannot put it back. Tested against
				// `positionOf` -- the enabled ones -- this used to be refused
				// as a sub-set holding something its root does not, so turning
				// one nuclide off made a model with any sub-set of the
				// nuclides fail to load, with a message about a list the
				// modeller had not touched.
				const off = list.enabled.filter((i) => !root.positionOf.has(i.name));
				if (off.length) {
					list.enabled = list.enabled.filter((i) => root.positionOf.has(i.name));
					list.size = list.enabled.length;
					list.positionOf = new Map(list.enabled.map((i, k) => [i.name, k]));
				}
			}
			if (list.mapping) {
				const target = this.lists.get(list.mapping.to);
				if (!target) {
					throw new IndexError(
						`Index list '${list.name}' maps to '${list.mapping.to}', ` +
						`which does not exist`, list.name,
					);
				}
			}
		}

		// Every list is placed against a *root* list, with a translation each
		// way. Two lists are then related whenever their roots agree, however
		// many steps apart they are -- which is what makes an element list
		// readable from a sub-set of the nuclides.
		for (const list of this.lists.values()) this._place(list);

		this._placeScenarios();
	}

	/**
	 * Works out a list's root and its translation to and from it.
	 *
	 * A list is defined against another in one of two ways, and the two point
	 * in opposite directions:
	 *
	 *   sub-set   every index of this list is an index of the parent, so the
	 *             translation up is total and the one down is partial
	 *   mapping   several indices of the parent share one index here -- a
	 *             nuclide has one element, an element has many nuclides -- so
	 *             the translation *down* is the total one
	 *
	 * Following the chain to a root and composing gives one pair of tables per
	 * list, and `relate` is then the same two lookups whatever the lists are.
	 */
	_place(list, seen = new Set()) {
		if (list.rootName) return list;
		if (seen.has(list.name)) {
			throw new IndexError(
				`Index list '${list.name}' is defined in terms of itself`, list.name,
			);
		}
		seen.add(list.name);

		const parentName = list.sub_set_of ?? list.mapping?.to ?? null;
		if (!parentName) {
			list.rootName = list.name;
			list.up = identity(list.size);
			list.down = identity(list.size);
			return list;
		}

		const parent = this._place(this.get(parentName), seen);
		// One step: this list <-> its parent.
		const stepUp = list.sub_set_of
			? this._byName(list, parent)
			: this._mappedUp(list, parent);
		const stepDown = list.sub_set_of
			? this._byName(parent, list)
			: this._mappedDown(list, parent);

		list.rootName = parent.rootName;
		list.up = compose(stepUp, parent.up);
		list.down = compose(parent.down, stepDown);
		return list;
	}

	/** For each position of `a`, the position of the same name in `b`. */
	// eslint-disable-next-line class-methods-use-this
	_byName(a, b) {
		const table = new Int32Array(a.size).fill(-1);
		a.enabled.forEach((idx, k) => {
			const pos = b.positionOf.get(idx.name);
			table[k] = pos === undefined ? -1 : pos;
		});
		return table;
	}

	/**
	 * For each index of a mapped list, one index of its parent.
	 *
	 * A mapping is many-to-one the other way, so this direction has to pick a
	 * representative. The first pair the file names is taken, which at least
	 * makes the choice stable and inspectable; going the other way is exact.
	 */
	// eslint-disable-next-line class-methods-use-this
	_mappedUp(list, parent) {
		const table = new Int32Array(list.size).fill(-1);
		for (const pair of list.mapping.pairs ?? []) {
			const k = list.positionOf.get(pair.from);
			const pos = parent.positionOf.get(pair.to);
			if (k === undefined || pos === undefined || table[k] >= 0) continue;
			table[k] = pos;
		}
		return table;
	}

	/** For each index of the parent, the index of the mapped list it belongs to. */
	// eslint-disable-next-line class-methods-use-this
	_mappedDown(list, parent) {
		const table = new Int32Array(parent.size).fill(-1);
		for (const pair of list.mapping.pairs ?? []) {
			const k = parent.positionOf.get(pair.to);
			const pos = list.positionOf.get(pair.from);
			if (k === undefined || pos === undefined) continue;
			table[k] = pos;
		}
		return table;
	}

	/**
	 * The indices of `from` that `dim` has no counterpart for -- what a
	 * partial translation is missing, so the message can name it rather than
	 * leaving the modeller to work out which nuclide was left out.
	 */
	missingFrom(dim, from) {
		const rel = this.relate(dim, from);
		if (!rel || rel.kind === 'same') return [];
		const names = this.indexNames(from);
		const out = [];
		for (let k = 0; k < rel.table.length; k++) {
			if (rel.table[k] < 0 && names[k] !== undefined) out.push(names[k]);
		}
		return out.length ? out : ['missing indices'];
	}

	has(name) { return this.lists.has(name); }

	get(name) {
		const l = this.lists.get(name);
		if (!l) throw new IndexError(`No index list named '${name}'`);
		return l;
	}

	names() { return [...this.order]; }

	size(name) { return this.get(name).size; }

	/** Enabled index names, in order. */
	indexNames(name) { return this.get(name).enabled.map((i) => i.name); }

	/** The list flagged as holding materials -- the root of the decay dimension. */
	materialList() {
		for (const name of this.order) {
			if (this.lists.get(name).for_contaminants) return this.lists.get(name);
		}
		return null;
	}

	/** The sub-set of it that has half-lives, or null in a model with none. */
	nuclideList() {
		for (const name of this.order) {
			if (this.lists.get(name).for_nuclides) return this.lists.get(name);
		}
		return null;
	}

	/**
	 * Row-major strides for an ordered list of dimension names, matching the
	 * order the block declares them in.
	 */
	strides(dims) {
		const sizes = dims.map((d) => this.size(d));
		const strides = new Array(dims.length).fill(1);
		for (let i = dims.length - 2; i >= 0; i--) {
			strides[i] = strides[i + 1] * sizes[i + 1];
		}
		return strides;
	}

	/** Total number of values a block of these dimensions holds. */
	width(dims) {
		return dims.reduce((n, d) => n * this.size(d), 1);
	}

	/** Offset of an index tuple (array of index names) within a block. */
	offsetOf(dims, tuple) {
		const strides = this.strides(dims);
		let off = 0;
		for (let i = 0; i < dims.length; i++) {
			const list = this.get(dims[i]);
			const pos = list.positionOf.get(tuple[i]);
			if (pos === undefined) {
				throw new IndexError(
					`'${tuple[i]}' is not an enabled index of '${dims[i]}'`,
				);
			}
			off += pos * strides[i];
		}
		return off;
	}

	/** The index tuple at an offset -- the inverse of offsetOf. */
	tupleAt(dims, offset) {
		const strides = this.strides(dims);
		const out = [];
		let rest = offset;
		for (let i = 0; i < dims.length; i++) {
			const k = Math.floor(rest / strides[i]);
			rest -= k * strides[i];
			out.push(this.get(dims[i]).enabled[k].name);
		}
		return out;
	}

	/** Every index tuple of a block, in offset order. */
	*tuples(dims) {
		const total = this.width(dims);
		for (let i = 0; i < total; i++) yield this.tupleAt(dims, i);
	}

	/**
	 * Can a value indexed by `from` be read when we are positioned in `to`?
	 *
	 * Two lists are compatible when they are the same list, or when one is a
	 * sub-set of the other, or when one maps onto the other. Returns a
	 * descriptor saying how to translate a position in `to` into a position in
	 * `from`, or null when they are unrelated.
	 */
	relate(fromList, toList) {
		if (fromList === toList) return { kind: 'same' };

		const a = this.get(fromList);
		const b = this.get(toList);
		// Unrelated lists share no root, and no amount of table-building will
		// relate them. Saying so is the point: the build then reports which
		// dimension it could not carry rather than inventing a position.
		if (a.rootName !== b.rootName) return null;

		// Up out of the list we are standing in, down into the one we want.
		const table = new Int32Array(b.size).fill(-1);
		let partial = false;
		for (let k = 0; k < b.size; k++) {
			const root = b.up[k];
			const pos = root < 0 ? -1 : a.down[root];
			table[k] = pos;
			if (pos < 0) partial = true;
		}
		return { kind: 'map', table, partial };
	}

	/**
	 * Works out how to read a block of dimensions `targetDims` from inside a
	 * block of dimensions `sourceDims`.
	 *
	 * Returns one term per target dimension:
	 *   { stride, from: <position in sourceDims> }          direct carry
	 *   { stride, from: <position>, table: Int32Array }     via a sub-set or mapping
	 *   { stride, fixed: <position> }                       an explicit index
	 *
	 * `fixedIndices` supplies explicit choices by list name, from `Y[Cs-137]`.
	 * Throws when a target dimension cannot be resolved -- that is the
	 * "which one did you mean" case, and it is better to say so than to guess.
	 */
	projection(sourceDims, targetDims, fixedIndices = {}, context = {}) {
		const strides = this.strides(targetDims);
		const terms = [];

		for (let i = 0; i < targetDims.length; i++) {
			const dim = targetDims[i];
			const stride = strides[i];

			// An explicit index wins.
			if (Object.prototype.hasOwnProperty.call(fixedIndices, dim)) {
				const pos = this.get(dim).positionOf.get(fixedIndices[dim]);
				if (pos === undefined) {
					throw new IndexError(
						`'${fixedIndices[dim]}' is not an enabled index of '${dim}'`,
					);
				}
				terms.push({ stride, fixed: pos, dim });
				continue;
			}

			// Otherwise carry it from the source, directly or through a table.
			// A *total* relation is preferred over a partial one: if some
			// other source dimension can reach this one for every index, that
			// is the translation to use.
			let best = null;
			for (let s = 0; s < sourceDims.length; s++) {
				const rel = this.relate(dim, sourceDims[s]);
				if (!rel) continue;
				if (rel.kind === 'same') { best = { stride, from: s, dim }; break; }
				const here = { stride, from: s, table: rel.table, dim, partial: rel.partial };
				if (!best || (best.partial && !here.partial)) best = here;
			}

			// A partial translation has no answer for at least one index, and
			// its table says so with a -1. Nothing downstream looks at that:
			// the emitters write `MAPS[k][v]` straight into an offset, so the
			// -1 became `base - stride` -- a valid slot belonging to a
			// different block, read as if it were this one. A sub-set that
			// covers two of three nuclides handed the third an unrelated
			// parameter's number, with no error and no NaN. There is no
			// position to compute here, so the model has to say what it means.
			if (best && best.partial) {
				const what = context.target ? `'${context.target}'` : 'that block';
				const where = context.owner ? `'${context.owner}'` : 'this block';
				const from = sourceDims[best.from];
				throw new IndexError(
					`${what} is indexed by '${dim}', which does not cover every index of `
					+ `'${from}' -- so for some of them ${where} has no value to read. `
					+ `Give '${dim}' the missing ${this.missingFrom(dim, from).join(', ')}, `
					+ `or write an explicit index, as in `
					+ `${context.target ?? 'block'}[${this.indexNames(dim)[0] ?? 'index'}].`,
					dim,
				);
			}

			if (!best) {
				const what = context.target ? `'${context.target}'` : 'that block';
				const where = context.owner ? `'${context.owner}'` : 'this block';
				throw new IndexError(
					`${what} is indexed by '${dim}', which ${where} is not indexed by and ` +
					`cannot reach. Give an explicit index, as in ` +
					`${context.target ?? 'block'}[${this.indexNames(dim)[0] ?? 'index'}], ` +
					`or add '${dim}' to ${where}.`,
					dim,
				);
			}
			terms.push(best);
		}
		return terms;
	}

	/** Ordered index-list names for a set of dimensions, deduplicated. */
	static normaliseDims(dims) {
		const seen = new Set();
		const out = [];
		for (const d of dims ?? []) {
			if (seen.has(d)) {
				throw new IndexError(`Index list '${d}' is used twice on the same block`);
			}
			seen.add(d);
			out.push(d);
		}
		return out;
	}
}

/**
 * Turns the `nuclides: [...]` shorthand into a real index list.
 *
 * The shorthand came first in this tool and every existing model uses it, so
 * it stays supported: it is exactly an index list flagged as the material
 * dimension, which blocks pick up unless they opt out with
 * `per_nuclide: false`. A file written when that list was called `Nuclide`
 * names it that way in its blocks too; both are renamed as the file is read.
 * See `renameBuiltInLists`.
 */
export const NUCLIDE_LIST = 'Radionuclides';

/**
 * The catalogue the radionuclides are a sub-set of.
 *
 * Ecolego keeps three material dimensions, built in and maintained from one
 * list of materials: `Materials` is every material the model knows,
 * `Radionuclides` the sub-set of them that has a half-life, and `Elements` a
 * grouping of the first. the rule for a new contaminant is where they
 * are kept in step -- every material goes in the catalogue, and one that is a
 * nuclide goes in the sub-set and brings its element with it.
 *
 * A material that is not a radionuclide is not a curiosity: the corpus here
 * carries stable carbon beside C-14 (`Carbon_12`, in kgC), water, and a
 * Lotka-Volterra model whose two materials are `Rabbit` and `Fox`. A
 * compartment indexed by the catalogue holds all of them and decays the ones
 * that decay.
 */
/**
 * Called `Contaminants` rather than Ecolego's `Materials`.
 *
 * The three tools this tool is read against do not agree, and two of the three
 * say contaminant: AMBER is a contaminant transport code and says so
 * throughout, GoldSim's module is Contaminant Transport (its *element* is
 * `Species`, which is no use here -- in a biosphere model, where compartments
 * are lakes and soils and organisms, "species" reads as *organism*), and
 * Ecolego says material. `Contaminants` is what a modeller opening this expects
 * the transported things to be called.
 *
 * What it costs is the model whose material is not a contaminant -- the stable
 * carbon, the water, the Lotka-Volterra rabbit. They are still allowed and
 * still work; they are just filed under a name that is a shade too specific
 * for them. Read as "what is being transported", which is what the list is.
 *
 * A file written under the old name -- and every Ecolego import, whose own
 * list is `Materials` -- is renamed as it is read. See `renameBuiltInLists`.
 */
export const MATERIAL_LIST = 'Contaminants';

/** The element dimension that comes with the nuclide one. */
export const ELEMENT_LIST = 'Elements';

/**
 * What this tool used to call the two lists it builds in.
 *
 * `Nuclide` and `Element` were this tool's own names for them; Ecolego calls
 * them `Radionuclides` and `Elements`, and so does every real file -- the
 * index lists of one small vault model are `Materials`, `Radionuclides` (a sub-set of
 * it) and `Elements` (a mapping onto it). Reading a model whose dimensions are
 * spelled one way and writing one spelled the other is a difference nobody
 * asked for, so the built-in names are now Ecolego's and a file written under
 * the old ones is renamed as it is read. See `renameBuiltInLists`.
 */
const WAS = {
	[NUCLIDE_LIST]: 'Nuclide', [ELEMENT_LIST]: 'Element', [MATERIAL_LIST]: 'Materials',
};

/**
 * Renames the built-in lists in a raw project written under their old names.
 *
 * Only the lists this tool built in: the radionuclide dimension, whether it is
 * written down as a list flagged `for_materials` or implied by the `nuclides:`
 * shorthand, and the element dimension that comes with it. A list called
 * `Nuclide` that is somebody's own dimension of something else is left alone,
 * and so is either of them in a model that already has a list under the new
 * name -- renaming into a name that is taken is not a rename, it is a
 * collision.
 *
 * Everywhere the name appears: the list itself, the lists defined from it, the
 * dimensions each block declares, and the keys of the values they hold per
 * index. The same places `renameIndexList` touches, which is the editor's own
 * rename -- written again here rather than reached for, because this runs on a
 * raw file before anything has been resolved, and it must not mutate what it
 * is given.
 */
export function renameBuiltInLists(raw) {
	if (!raw || typeof raw !== 'object') return raw;
	const lists = Array.isArray(raw.index_lists) ? raw.index_lists : [];
	const taken = new Set(lists.map((l) => l?.name));
	// The flag under any of its spellings: this runs before the key migration,
	// so a file may still say `for_materials` or even `forMaterials`.
	const flagged = (l) => !!(l?.for_contaminants ?? l?.for_materials ?? l?.forMaterials);
	const material = lists.find(flagged);
	const map = new Map();
	const rename = (to) => {
		const from = WAS[to];
		if (!from || taken.has(to)) return;
		map.set(from, to);
	};
	// The radionuclide dimension, however it got there.
	if (material ? material.name === WAS[NUCLIDE_LIST]
		: (raw.nuclides ?? []).length > 0) rename(NUCLIDE_LIST);
	// The element dimension: flagged as such, or a list of that name mapped
	// onto the material one, which is what this tool's derived list is.
	const element = lists.find((l) => l?.name === WAS[ELEMENT_LIST]
		&& (l.for_elements || (l.mapping?.to && l.mapping.to === material?.name)));
	if (element) rename(ELEMENT_LIST);
	// The catalogue, which Ecolego calls `Materials` and this tool now calls
	// `Contaminants`: renamed whether it arrived from an older file of this
	// tool's or straight out of a .eco, since both spell it Ecolego's way.
	if (material && material.name === WAS[MATERIAL_LIST]) rename(MATERIAL_LIST);
	if (!map.size) return raw;

	const to = (name) => map.get(name) ?? name;
	const out = { ...raw };
	if (lists.length) {
		out.index_lists = lists.map((l) => {
			if (!l || typeof l !== 'object') return l;
			const next = { ...l, name: to(l.name) };
			if (l.sub_set_of) next.sub_set_of = to(l.sub_set_of);
			if (l.mapping?.to) next.mapping = { ...l.mapping, to: to(l.mapping.to) };
			return next;
		});
	}
	for (const [key, value] of Object.entries(raw)) {
		if (key === 'index_lists' || !Array.isArray(value)) continue;
		let changed = false;
		const blocks = value.map((b) => {
			if (!b || typeof b !== 'object') return b;
			const dims = Array.isArray(b.index_lists) ? b.index_lists : null;
			const needsDims = dims?.some((d) => map.has(d));
			const needsEntries = Array.isArray(b.entries)
				&& b.entries.some((e) => e?.index && Object.keys(e.index).some((d) => map.has(d)));
			if (!needsDims && !needsEntries) return b;
			changed = true;
			const next = { ...b };
			if (needsDims) next.index_lists = dims.map(to);
			if (needsEntries) {
				next.entries = b.entries.map((e) => (e?.index
					? {
						...e,
						index: Object.fromEntries(
							Object.entries(e.index).map(([d, i]) => [to(d), i]),
						),
					}
					: e));
			}
			return next;
		});
		if (changed) out[key] = blocks;
	}
	return out;
}

/**
 * Adds the element list that goes with the material list.
 *
 * Chemistry is a property of the element, not of the isotope: a sorption
 * coefficient, a concentration ratio, a partition factor are all per element
 * while inventory and decay are per nuclide. Ecolego therefore keeps an
 * `ELEMENTS` list beside the materials, mapped onto it, and real models lean
 * on it heavily -- it is what `Kd_rock[Elements]` and `f_water_D[Species]`
 * are indexed by.
 *
 * So this tool derives one rather than making every model declare it. It is
 * *derived*, not stored: its indices and its mapping follow the nuclide list,
 * so enabling a nuclide brings its element with it and nothing can fall out of
 * step. `Project.toJSON` leaves it out of the saved file for the same reason.
 *
 * A model that declares its own element list -- an imported one, or a model
 * that needs `C-14 organic` and `C-14 inorganic` kept apart -- keeps it, and
 * nothing is derived.
 */
export function deriveElements(lists) {
	const all = lists ?? [];
	const material = all.find((l) => l.for_contaminants);
	if (!material) return all;

	// A model that already has an element dimension keeps it, whether it says
	// so with the flag or only by its name. Deriving a second one beside it
	// would put two nearly identical lists in every block's dimension picker.
	const already = all.some((l) => l.for_elements
		|| l.name === ELEMENT_LIST || l.name === WAS[ELEMENT_LIST]);
	if (already) return all;

	// Every material, not only the ones that decay. A mapping has to cover the
	// list it groups: a parameter indexed by the elements, read from a block
	// indexed by the materials, has no cell to read at a material no element
	// stands for -- and the build says so and stops. So stable carbon, water
	// and Lotka-Volterra's rabbits each get one, and chemistry can be written
	// for them like anything else.
	//
	// The element of a name that is a nuclide's is its symbol, so C-12 joins
	// C-14 under `C` -- the two are the same element and one sorption
	// coefficient is right for both. A name that is not a nuclide's is its own
	// element: there is nothing else it could belong to.
	const names = [];
	const pairs = [];
	for (const raw of material.indices ?? []) {
		const nuclide = typeof raw === 'string' ? raw : raw?.name;
		// A disabled nuclide takes no part in the simulation, so neither does
		// its element -- unless another isotope of it is still on.
		if (typeof raw === 'object' && raw?.enabled === false) continue;
		const el = elementOf(nuclide) ?? nuclide;
		if (!el) continue;
		if (!names.includes(el)) names.push(el);
		pairs.push({ from: el, to: nuclide });
	}
	if (!names.length) return all;

	return [...all, {
		name: ELEMENT_LIST,
		for_elements: true,
		derived: true,
		comment: `One index per element of ${material.name}, kept in step with it.`,
		mapping: { to: material.name, pairs },
		indices: names.map((n) => ({ name: n, enabled: true })),
	}];
}

/**
 * Tells the two material roles apart in a file that has them as one.
 *
 * `for_materials` used to mean both: the dimension decay runs along *and* the
 * list the radionuclide database adds to, because this tool had only one list
 * where Ecolego has two. Ecolego's are `Materials`, every material the model
 * knows, and `Radionuclides`, the sub-set of them that has a half-life. So
 * `for_materials` now marks the catalogue -- which is what the word says --
 * and `for_nuclides` the sub-set.
 *
 * A file written under the old meaning is in one of three shapes:
 *
 *   imported   the flag is on `Radionuclides`, already a sub-set of
 *              `Materials`: the two only have to be told apart
 *   imported   the flag is on `Materials` because the file's radionuclide
 *              list was empty, and the sub-set is there unflagged
 *   this tool  the flag is on `Radionuclides` and there is no catalogue at
 *              all: one is made above it, holding the same materials
 *
 * Every block keeps the dimension it was indexed by in all three, and the
 * model computes what it computed: the catalogue starts out holding exactly
 * what the radionuclide list holds, so a compartment on either has the same
 * width and the same names in the same order.
 *
 * Non-mutating, like `renameBuiltInLists` beside it, and for the same reason:
 * it runs on a raw file before anything has been resolved.
 */
/**
 * `want`, or the first free name based on it.
 *
 * No separator before the number: an index list name is an identifier -- the
 * dimensions a block declares are written in equations -- and `Materials 2`
 * is three tokens. `uniqueIndexListName` in the editor spells it the same way.
 */
function freeName(taken, want) {
	const used = new Set(taken);
	let name = want;
	for (let n = 2; used.has(name); n++) name = `${want}${n}`;
	return name;
}

export function splitMaterialRoles(raw) {
	if (!raw || typeof raw !== 'object') return raw;
	const lists = Array.isArray(raw.index_lists) ? raw.index_lists : [];
	// Already two roles, or no material role at all to split.
	if (!lists.length || lists.some((l) => l?.for_nuclides)) return raw;
	const flagged = lists.find((l) => l?.for_contaminants);
	if (!flagged) return raw;

	const asNuclides = (l) => {
		const next = { ...l, for_nuclides: true };
		delete next.for_contaminants;
		return next;
	};

	let next = null;
	let root = null;

	// The catalogue is above it: the flag is on a sub-set of something.
	const parent = flagged.sub_set_of
		? lists.find((l) => l?.name === flagged.sub_set_of)
		: null;
	if (parent) {
		root = parent.name;
		next = lists.map((l) => (l === flagged ? asNuclides(l)
			: l === parent ? { ...l, for_contaminants: true } : l));
	} else {
		// The flag is already on a root, and the radionuclides are a sub-set
		// of it that nothing has named. This is the file whose radionuclide
		// list the importer found empty -- `SiloWithBottom_and_farfield.eco`
		// is one -- so the catalogue was the only list that could hold a role.
		const sub = lists.find((l) => l?.sub_set_of === flagged.name
			&& (l.name === NUCLIDE_LIST || l.name === WAS[NUCLIDE_LIST]));
		if (sub) {
			root = flagged.name;
			next = lists.map((l) => (l === sub ? { ...l, for_nuclides: true } : l));
		} else {
			// A lone list that is already *called* the catalogue is one: what
			// it is missing is the radionuclide sub-set, which the editor adds
			// empty. Demoting it would put a second catalogue above a list
			// named `Materials`, which is two lists claiming one name's job.
			if (flagged.name === MATERIAL_LIST) return raw;
			// No catalogue anywhere: this tool's own file, which had one list
			// doing both jobs. The catalogue is made holding what that list
			// holds, the flag moves to it, and the radionuclides become a
			// sub-set -- which is what they always were, unwritten.
			root = freeName(lists.map((l) => l?.name), MATERIAL_LIST);
			const catalogue = {
				name: root,
				for_contaminants: true,
				comment: `Every material the model knows. The radionuclides among `
					+ `them are in ${flagged.name}.`,
				indices: (flagged.indices ?? []).map((i) => (typeof i === 'string'
					? { name: i, enabled: true }
					: { ...i })),
			};
			next = [];
			for (const l of lists) {
				if (l !== flagged) { next.push(l); continue; }
				// Immediately above it, where the panel reads root then sub-set.
				next.push(catalogue, { ...asNuclides(l), sub_set_of: root });
			}
		}
	}

	// A sub-set of the radionuclides is now a sub-set of a sub-set, which
	// neither this tool nor Ecolego has: `IndexListView` greys out "create
	// sub-set" on a list that is already one, so a model's own selection of
	// nuclides is taken from the catalogue there. Re-pointed rather than
	// refused -- the catalogue holds every name the radionuclide list holds,
	// so the selection is the same selection and everything indexed by it is
	// untouched.
	const nuclides = next.find((l) => l?.for_nuclides)?.name ?? null;
	if (!nuclides || nuclides === root) return { ...raw, index_lists: next };
	return {
		...raw,
		index_lists: next.map((l) => {
			if (!l || l.for_nuclides) return l;
			if (l.sub_set_of === nuclides) return { ...l, sub_set_of: root };
			// A grouping of the nuclides is a grouping of the catalogue: its
			// pairs name indices, and those names are in both.
			if (l.mapping?.to === nuclides) {
				return { ...l, mapping: { ...l.mapping, to: root } };
			}
			return l;
		}),
	};
}

/**
 * The two dimensions a model has by virtue of what is in it.
 *
 * `Compartments` has one index per compartment and `Transfers` one per
 * transfer, both named by the block's qualified name -- `NearField.Water` --
 * because that is what identifies a block, and two sub-systems may each have a
 * `Water`.
 *
 * WHY. A great deal of what a model needs is per compartment or per transfer:
 * a sorption coefficient for each compartment, a rate coefficient for each
 * transfer, a volume, a depth. Without these lists that is written as one
 * parameter per compartment -- forty blocks whose only difference is which
 * compartment they belong to -- or as forty entries on a list somebody has to
 * keep in step with the model by hand. With them it is one parameter with a
 * column of values, and the column follows the model: add a compartment and it
 * gains a row, rename one and the row follows.
 *
 * Derived, not stored, for exactly the reason the element list is: there is
 * nothing here that is not already in the model, so writing it down would only
 * create something that could fall out of step. `Project.toJSON` leaves them
 * out.
 *
 * These are this tool's, not Ecolego's: Ecolego has no such list, and a model
 * that uses one cannot be written back to a .eco file as it stands. See
 * INTERNALS.md.
 */
export const COMPARTMENT_LIST = 'Compartments';
export const TRANSFER_LIST = 'Transfers';

/**
 * The words that stand for a transfer's own two ends inside its equations.
 *
 * `Kd[_source_]` is the donor's value of a compartment-indexed block and
 * `Kd[_target_]` the receiver's. They are not index names -- no list holds
 * them -- so the engine translates them into the compartment they mean before
 * anything tries to match them against a list. Underscored at both ends so
 * they cannot collide with a block: a name like that is not one anybody writes,
 * and Ecolego would not accept it as one.
 *
 * Here rather than in the engine because the editor needs them too -- they are
 * offered while an equation is being typed -- and the editor has no business
 * importing the builder to find out what they are called.
 */
export const SOURCE_INDEX = '_source_';
export const TARGET_INDEX = '_target_';

/** The qualified name of a block, as an index name. */
const blockIndexName = (b) => (b?.system ? `${b.system}.${b.name}` : b?.name);

/**
 * Adds the compartment and transfer dimensions to a set of lists.
 *
 * @param lists the model's own lists, already desugared
 * @param model the raw project or a Project: both carry `compartments` and
 *   `transfers` arrays of blocks with a name and a sub-system
 */
/**
 * The list a list is derived from, by name, or null when it is a root.
 *
 * One reader for the two spellings. A mapping is `{ to, pairs }` here and in
 * every file this tool writes, and reading it as a name -- which two walkers
 * did -- stopped the walk at the first mapped list, so a grouping of the
 * scenarios looked like an ordinary dimension. A bare name is accepted
 * because a hand-written file may say `mapping: "Cases"` and meaning it is
 * obvious.
 */
export function parentListName(list) {
	if (!list) return null;
	if (list.sub_set_of) return list.sub_set_of;
	const m = list.mapping;
	if (!m) return null;
	return typeof m === 'string' ? m : m.to ?? null;
}

export function deriveBlockLists(lists, model) {
	const out = [...(lists ?? [])];
	for (const [name, collection, what] of [
		[COMPARTMENT_LIST, 'compartments', 'compartment'],
		[TRANSFER_LIST, 'transfers', 'transfer'],
	]) {
		// A model that declares a list of this name keeps it, the same
		// bargain the element dimension makes: two nearly identical lists in
		// every block's dimension picker is worse than not deriving one.
		if (out.some((l) => l.name === name)) continue;
		// The states a transport chain adds behind its two ends are marked
		// `hidden`, and are not indices: Ecolego's lists hold Begin and End
		// and nothing in between, and a value per compartment has no entry
		// for a slice nobody can name. See ../sim/transport.js.
		const names = (model?.[collection] ?? [])
			.filter((b) => !b?.hidden)
			.map(blockIndexName)
			.filter((n) => typeof n === 'string' && n);
		// Nothing to be indexed by. A list of no indices is not a dimension:
		// a block carrying it would hold no values at all.
		if (!names.length) continue;
		out.push({
			name,
			derived: true,
			auto: collection,
			note: `One index per ${what} in the model — the ${what}s are the `
				+ `indices, so there is nothing to edit here. Add a ${what} and `
				+ `this list gains an index; rename one and the index follows.`,
			indices: names.map((n) => ({ name: n, enabled: true })),
		});
	}
	return out;
}

/**
 * The kinds of block that may be indexed by the derived block dimensions.
 *
 * `Compartments` and `Transfers` are made of the model's own blocks, and the
 * blocks they are made of already have a position in them by being themselves:
 * a compartment *is* one of the compartments, which is what lets a
 * per-compartment parameter be read inside one with no index at all. Letting a
 * compartment also be *indexed by* them would mean one state per pair of
 * compartments, and a transfer indexed by the transfers is the same nonsense
 * one step along.
 *
 * What is left is the blocks that hold a value for other blocks to read -- an
 * expression, a parameter, a lookup table -- and the two that combine them.
 * Those are what a column of per-compartment or per-transfer values is for.
 */
export const AUTO_DIM_KINDS = new Set([
	'expression', 'parameter', 'lookup', 'block_reduction', 'index_reduction',
]);

/** Whether a block of this kind may be indexed by this list. */
export function listApplies(list, kind) {
	// A list that is not there is not one anything may be indexed by. It read
	// `!list?.auto`, which answers "yes, go ahead" to a question about
	// nothing -- and a caller that looked a list up and got nothing is exactly
	// the caller whose block should not be built.
	if (!list) return false;
	if (!list.auto) return true;
	return AUTO_DIM_KINDS.has(kind);
}

/** Why not, in words, for a list this kind cannot carry. */
export function listAppliesWhy(list, kind) {
	if (listApplies(list, kind)) return '';
	if (!list) return 'That index list is not in this model.';
	const one = list.auto === 'compartments' ? 'compartment' : 'transfer';
	const own = kind === one
		? `A ${one} is one of them already: that is what lets a value indexed by `
			+ `'${list.name}' be read inside a ${one} with no index at all. `
		: '';
	return `'${list.name}' has one index per ${one}, and a ${String(kind).replace(/_/g, ' ')} `
		+ `cannot be indexed by them. ${own}Only an expression, a parameter, a lookup `
		+ `table, an aggregate or an index operation can.`;
}

/**
 * How a list reaches its root: the chain of lists above it, nearest first, and
 * whether a mapping is on the way.
 *
 * A sub-set is *part of* its parent -- `Radionuclides` out of `Materials`; a
 * mapping is a *grouping* of it -- `Elements` over the nuclides, a climate
 * class over its years. Either way the two are one dimension, which is what
 * `clashingDimensions` needs to know.
 */
export function lineage(lists, name) {
	let at = name;
	let mapped = false;
	const above = [];
	const seen = new Set();
	while (at && !seen.has(at)) {
		seen.add(at);
		const list = (lists ?? []).find((l) => l.name === at);
		const next = list?.mapping?.to ?? list?.sub_set_of ?? null;
		if (!next) break;
		if (list?.mapping?.to) mapped = true;
		above.push({ name: next, mapped: !!list?.mapping?.to });
		at = next;
	}
	return { root: at ?? name, mapped, above };
}

/**
 * The first pair of dimensions that are one dimension twice, or null.
 *
 * Ecolego's rule, from the rule for which lists are allowed: *"No object can
 * have two index lists whose root index list are the same. For example, the
 * two lists cannot both be sub-sets of AllMaterials."* A list and a sub-set of
 * it, a list and a grouping of it, two sub-sets of one list -- all of them
 * share a root, and a block indexed by two of them would be indexed by the
 * same dimension twice, with nothing in an equation to say which cell of which
 * is meant. None of the 87 real projects here does it.
 *
 * The same source adds one more pair, in `DimensionPanel`: *"An object cannot
 * be both transfer and compartment dependent."* The two lists made of the
 * model's own blocks are not the same dimension, but a value per compartment
 * per transfer is not a thing either program has a meaning for.
 *
 * @returns {{a: string, b: string, root: string, how: string}|null} `how` is
 *   `sub_set`, `grouping`, `siblings` or `blocks`
 */
export function clashingDimensions(lists, dims) {
	const seen = (dims ?? []).map((d) => ({ name: d, ...lineage(lists, d) }));
	const autoOf = (n) => (lists ?? []).find((l) => l.name === n)?.auto ?? null;
	for (let i = 0; i < seen.length; i++) {
		for (let j = i + 1; j < seen.length; j++) {
			const a = seen[i];
			const b = seen[j];
			if (a.name === b.name) continue;
			if (a.root === b.root) {
				// Which of the two is above the other, if either is: `below`
				// is the narrower list (the sub-set) or the coarser one (the
				// grouping), `above` the list it was made from.
				const bAboveA = a.above.find((x) => x.name === b.name);
				const aAboveB = b.above.find((x) => x.name === a.name);
				const link = bAboveA ?? aAboveB;
				const how = !link ? 'siblings' : link.mapped ? 'grouping' : 'sub_set';
				const below = bAboveA ? a.name : aAboveB ? b.name : null;
				const above = below === a.name ? b.name : below === b.name ? a.name : null;
				return { a: a.name, b: b.name, root: a.root, how, below, above };
			}
			const ra = autoOf(a.root);
			const rb = autoOf(b.root);
			if (ra && rb && ra !== rb) return { a: a.name, b: b.name, root: null, how: 'blocks' };
		}
	}
	return null;
}

/** Why not, in words. */
export function clashingDimensionsWhy(clash) {
	if (!clash) return '';
	const { a, b, root, how } = clash;
	if (how === 'blocks') {
		return `'${a}' has one index per compartment and '${b}' one per transfer, and a `
			+ 'block cannot be indexed by both: a value per compartment per transfer '
			+ 'is not a quantity the model has. Pick one.';
	}
	if (how === 'siblings') {
		return `'${a}' and '${b}' are both taken from '${root}', so a block indexed by `
			+ 'both would be indexed by the same dimension twice. Pick one.';
	}
	const { below, above } = clash;
	if (how === 'grouping') {
		return `'${below}' is a grouping of '${above}', so a block indexed by both would `
			+ 'be indexed by the same dimension twice, at two different granularities. '
			+ 'Pick one.';
	}
	return `'${below}' is a sub-set of '${above}', so a block indexed by both would be `
		+ 'indexed by the same dimension twice -- once over all of it and once over '
		+ 'part of it. Pick one: the longer list, or the shorter.';
}

/**
 * What a transfer between two blocks is indexed by: the indices both ends have.
 *
 * Not a choice: a transfer moves inventory out of one cell and into another,
 * so it exists exactly where there are two such cells, and the intersection
 * of the two ends' lists is the only thing a flux between them can mean. The
 * desktop tool indexes its transfers the same way, and refuses a connection
 * outright unless the two ends correspond position for position -- the same
 * list, or one a sub-set of the other with a shared root:
 *
 *   one end outside the model   the other end's dimensions, whole
 *   the same list               that list
 *   one a sub-set of the other  the sub-set, which *is* the intersection --
 *                               the names in it are all in its root, and no
 *                               other name is in both
 *
 * Positions are matched by **root**, not by order, so a transfer from
 * `A[Nuclide, Object]` into `B[Object, Nuclide]` still lines its dimensions
 * up.
 *
 * The scenario dimension is left out of the whole computation: one scenario
 * is live at a time, so it is not an axis a flux can vary along.
 *
 * @param from  the donor's dimensions, or null for the model boundary
 * @param to    the receiver's dimensions, or null
 * @returns `{ dims, shared }` -- `shared` naming the positions where the two
 *   ends differed and the intersection had to be taken -- or **null** where
 *   the ends do not correspond and no list of this model holds their common
 *   indices. Ecolego cannot build such a transfer at all; this tool can, and
 *   leaves it to say what it is indexed by itself.
 */
export function sharedDims(lists, from, to) {
	const all = lists ?? [];
	const plain = (dims) => (dims ?? []).filter((d) => {
		const list = all.find((l) => l.name === d);
		return !list?.for_scenarios;
	});
	if (from == null && to == null) return null;
	if (from == null || to == null) {
		return { dims: plain(from ?? to), shared: [] };
	}
	const a = plain(from);
	const b = plain(to);
	// Ecolego refuses a transfer whose ends are of different dimension, so
	// there is no rule to follow for one: whatever this model says it is
	// indexed by is the only answer there is.
	if (a.length !== b.length) return null;
	if (!a.length) return { dims: [], shared: [] };

	const rootOf = (name) => lineage(all, name).root;
	// The target's lists against the source's, by root.
	const rest = [...b];
	const matched = a.map((s) => {
		const at = rest.findIndex((t) => rootOf(t) === rootOf(s));
		return at < 0 ? null : rest.splice(at, 1)[0];
	});

	const dims = [];
	const shared = [];
	for (let i = 0; i < a.length; i++) {
		const s = a[i];
		const t = matched[i];
		if (t == null) return null;
		if (s === t) { dims.push(s); continue; }
		const ls = all.find((l) => l.name === s);
		const lt = all.find((l) => l.name === t);
		const narrower = ls?.sub_set_of === t ? s : lt?.sub_set_of === s ? t : null;
		// Two sub-sets of one root overlap in a set of names no list of this
		// model holds. Ecolego builds one on the spot -- an
		// `IntersectionIndexList` with no name -- and this tool has nowhere to
		// put it, so it says it cannot rather than picking one of the two.
		if (!narrower) return null;
		dims.push(narrower);
		shared.push({ from: s, to: t, dims: narrower });
	}
	return { dims, shared };
}

/**
 * The dimensions a flux would have to add up over to reach one of its ends.
 *
 * A transfer is indexed by what its two ends have in common, and the engine
 * walks that index space once per flux: for each combination it reads the
 * donor's cell, subtracts, and adds to the target's. When the flux carries a
 * dimension one end has not got, that end's offset does not move as the
 * dimension is walked, so every combination lands in the same slot -- the
 * fluxes are added up on the way into a target, and taken out of a donor once
 * per index. Mass is conserved either way; what is lost is that the model ever
 * said so.
 *
 * Ecolego cannot express it at all: it refuses a pair
 * whose ends are of different dimension before the connection is made, and
 * the dimension rule then pairs the two lists off by
 * root. So this is a shape of our own, allowed only where a model asks for it
 * by name -- `sum_extra_indices` on the flux.
 *
 * Relatedness is by root, as `IndexSpace.relate` has it: a sub-set or a
 * mapping of a list the end carries is reachable and is not summed over. A
 * scenario dimension is not part of the comparison, exactly as it is not in
 * `sharedDims` -- one index of it is live at a time, so it multiplies nothing.
 *
 * @param {object[]} lists the model's index lists, derived
 * @param {string[]} fluxDims what the transfer or source is indexed by
 * @param {string[]} endDims what the compartment or path at that end is
 * @returns {string[]} the flux's dimensions that end cannot follow
 */
export function summedDims(lists, fluxDims, endDims) {
	const all = lists ?? [];
	const plain = (dims) => (dims ?? []).filter(
		(d) => !all.find((l) => l.name === d)?.for_scenarios,
	);
	const rootOf = (name) => lineage(all, name).root;
	const roots = new Set(plain(endDims).map(rootOf));
	return plain(fluxDims).filter((d) => !roots.has(rootOf(d)));
}

/**
 * Why a flux that `summedDims` found something for will not build.
 *
 * The pair to `summedDims`, as `clashingDimensionsWhy` is to
 * `clashingDimensions`: one wording, so the file gate and the editor say the
 * same thing about the same model. The two ends read differently because they
 * are different mistakes to make -- one delivers a total, the other draws the
 * same cell down several times -- and a reader who meant neither needs to know
 * which one they have written.
 *
 * @param {{flux: string, end: 'from'|'to', endName: string,
 *          dims: string[], sizeOf?: (name: string) => number|null}} what
 */
export function summedDimsWhy({ flux, end, endName, dims, sizeOf = null }) {
	const named = dims.map((d) => `'${d}'`);
	const list = named.length > 1
		? `${named.slice(0, -1).join(', ')} and ${named[named.length - 1]}`
		: named[0];
	const sizes = dims.map((d) => sizeOf?.(d) ?? null);
	const count = sizes.every((n) => n) ? sizes.reduce((a, b) => a * b, 1) : null;
	const over = count ? `all ${count} of them` : 'all of them';
	const each = count ? `each of the ${count} of them` : 'each of them';
	return `'${flux}' is indexed by ${list}, which '${endName}' is not`
		+ (end === 'to'
			? `: the flux would be added up over ${over} and delivered into the one `
				+ `'${endName}' cell.`
			: `: the flux would be taken out of the one '${endName}' cell once for `
				+ `${each}.`)
		+ ` Give both ends the same dimensions, or tick "sum extra indices" on `
		+ `'${flux}' to ask for that total on purpose.`;
}

/**
 * Whether a dimension is one the nuclides decay along.
 *
 * The same rule the engine applies (`isNuclideDim` in ../sim/builder.js), and
 * it has to be: the editor decides whether to offer "handle decay" on a
 * compartment, and offering it where the engine will not apply it is a promise
 * the model does not keep.
 *
 * A list decays if it *is* the material dimension or a sub-set of it -- real
 * models keep a catalogue and the subset of it that decays, and index
 * compartments by either. A **mapping** of it is not: the element dimension
 * shares its root with the nuclides and decays along nothing, because one of
 * its indices stands for several nuclides at once.
 */
export function isDecayDim(lists, name, materialName) {
	if (!name || !materialName) return false;
	const list = (lists ?? []).find((l) => l.name === name);
	if (!list || list.mapping) return false;
	return lineage(lists, name).root === lineage(lists, materialName).root;
}

export function desugarNuclides(raw) {
	const nuclides = raw.nuclides ?? [];
	if (!nuclides.length) return raw.index_lists ?? [];

	const existing = raw.index_lists ?? [];
	// Nothing to desugar when the model already states its material dimension.
	// Adding a second one looked harmless -- no block was indexed by it -- but
	// `materialList()` returns the first, so decay and ingrowth were applied
	// along a list nothing used, and every imported model ran without decay.
	if (existing.some((l) => l.name === NUCLIDE_LIST || l.name === WAS[NUCLIDE_LIST]
		|| l.for_contaminants || l.for_nuclides)) return existing;

	// Both of them, because both always exist: the catalogue holds the
	// materials and the sub-set says which of them decay. The shorthand names
	// radionuclides, so here they are the same names -- a model grows them
	// apart by adding a material that is not one.
	const root = freeName(existing.map((l) => l?.name), MATERIAL_LIST);
	const indices = nuclides.map((n) => ({ name: n, enabled: true }));
	return [
		{
			name: root,
			for_contaminants: true,
			indices: indices.map((i) => ({ ...i })),
		},
		{
			name: NUCLIDE_LIST,
			for_nuclides: true,
			sub_set_of: root,
			indices,
		},
		...existing,
	];
}
