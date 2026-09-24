/**
 * Putting a spread on a setting that is not a parameter.
 *
 * **A distribution belongs to a parameter.** That is not an accident of this
 * implementation: a probabilistic run varies inputs, reports which of them
 * drove the spread, ranks them in a tornado and differentiates against them,
 * and every one of those wants the same thing -- a named quantity with one
 * value per realisation. `layout.parameters` is that list, and the sampler,
 * the sensitivity measures and `dy/dp` all read it.
 *
 * But most of a model's numbers are not parameters. A waste package's
 * characteristic life, a disruptive event's rate, a far-field path's aperture,
 * a compartment's initial inventory -- each is an *equation* on its own block,
 * and an equation has nowhere to keep a distribution and no slot for a sampler
 * to write into.
 *
 * **So this makes one a parameter.** Asking for a spread on a setting creates a
 * parameter holding the value it had, points the setting at it by name, and
 * hands back the parameter for the distribution to be put on. Nothing
 * downstream changes, because afterwards there is nothing unusual to handle:
 * it is a parameter like any other, and it appears in the probabilistic dialog,
 * in *what drove the spread*, in the tornado and in `dy/dp` immediately.
 *
 * It also makes the model say what it means. A canister life that varies is a
 * parameter of the assessment, and giving it a name is what lets a tornado plot
 * put a label on the bar.
 *
 * **What it will not do.** A setting has to be a plain number, or already a
 * reference to one parameter. `2 * canister_life` is an expression over
 * something that may already be uncertain, and replacing it with a parameter
 * would throw the expression away; the caller is told so rather than having its
 * arithmetic silently deleted.
 *
 * **The mode selectors are not settings.** A waste package's *way of failing*
 * and a disruptive event's *timing* -- Weibull, a constant rate, a Poisson
 * process -- are already distributions, over the packages or the occurrences
 * within one run. They are choices rather than numbers, and layering a second
 * distribution on top of one would be a different quantity than anyone means.
 * `UNCERTAIN_EXCLUDES` names them so the panels agree about it.
 */

import { addParameter, uniqueName, findBlock, blockNames, isEffectivelyEnabled } from './edit.js';
import { qualifiedName, systemOf, resolveReference } from './systems.js';
import { timingOf, describeDisruption } from './disruption.js';
import { failureOf, describeFailure } from './wastepackage.js';

/**
 * The block properties that are a choice among distributions, not a number.
 *
 * See the note above: these already carry a spread of their own.
 */
export const UNCERTAIN_EXCLUDES = new Set(['failure', 'timing']);

/** An identifier, and nothing else -- `canister_life`, or `NearField.Kd`. */
const BARE_NAME = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;

/**
 * Whether a setting's text is a number this can turn into a parameter.
 *
 * Blank counts: a setting left empty is a setting with no value yet, and
 * giving it an uncertain one is a reasonable thing to want.
 */
export function isPlainValue(text) {
	const t = String(text ?? '').trim();
	return t === '' || Number.isFinite(Number(t));
}

/**
 * The parameter a setting refers to, when it refers to exactly one and to
 * nothing else.
 *
 * This is what makes the control reversible: having made a setting uncertain,
 * opening it again finds the parameter behind it and edits *that* distribution
 * rather than creating a second one.
 *
 * @returns {object|null} the parameter block
 */
export function parameterBehind(project, block, text) {
	const t = String(text ?? '').trim();
	if (!BARE_NAME.test(t)) return null;
	// Resolved the way an equation would resolve it: a bare name inside a
	// sub-system means the nearer block of that name, not the root's.
	const known = new Set(blockNames(project));
	const qname = resolveReference(t, systemOf(block), (n) => known.has(n));
	if (!qname) return null;
	const found = findBlock(project, qname);
	// Every kind answers to a name; only a parameter carries a distribution.
	return found?.kind === 'parameter' ? found.block : null;
}

/**
 * What the state of a setting's uncertainty is, for a panel to draw.
 *
 * @returns {{can: boolean, parameter: object|null, why: string|null}}
 */
export function uncertaintyOf(project, block, key) {
	const text = block?.[key];
	const parameter = parameterBehind(project, block, text);
	if (parameter) return { can: true, parameter, why: null };
	if (isPlainValue(text)) return { can: true, parameter: null, why: null };
	return {
		can: false,
		parameter: null,
		why: 'This is an equation rather than a number, so it has no one value to '
			+ 'give a spread to. Give the quantity a parameter of its own first, and '
			+ 'put the spread on that.',
	};
}

/**
 * A name for the parameter a setting is about to get.
 *
 * `Canisters_fail_scale`, in the block's own sub-system, made unique. The
 * block's name and the setting's key, because the only place this name is ever
 * read is a list of inputs beside twenty others -- and `p7` there says nothing.
 */
export function nameFor(project, block, key) {
	const base = `${String(block?.name ?? 'x').replace(/[^A-Za-z0-9_]/g, '_')}_${key}`;
	return uniqueName(project, base, systemOf(block));
}

/**
 * Gives a setting a parameter of its own, carrying the value it had.
 *
 * The setting is rewritten to the parameter's name -- unqualified, since the
 * parameter is made in the block's own sub-system and a bare name means the
 * nearer one.
 *
 * @returns {object} the parameter block, for a distribution to be put on
 */
export function makeUncertain(project, block, key, { unit } = {}) {
	const state = uncertaintyOf(project, block, key);
	if (state.parameter) return state.parameter;
	if (!state.can) throw new Error(state.why);

	const text = String(block?.[key] ?? '').trim();
	const parameter = addParameter(project, {
		name: nameFor(project, block, key),
		value: text === '' ? '0' : text,
		system: systemOf(block),
	});
	// The unit travels with the value: it is the same quantity, and a
	// distribution editor draws its axis in it.
	if (unit) parameter.unit = unit;
	// A parameter made for one setting is not indexed by anything the setting
	// is not. `addParameter` gives it the model's default dimensions, which for
	// a nuclide-indexed model is the radionuclide list -- and a canister life
	// is one number however many nuclides are in the packages.
	parameter.index_lists = [];
	block[key] = parameter.name;
	return parameter;
}

/**
 * Takes the spread off, leaving the value behind.
 *
 * The parameter goes only if nothing else reads it and this made it: a
 * parameter somebody wired up themselves is theirs, and removing it because a
 * distribution was cleared would delete part of their model.
 */
export function clearUncertainty(project, block, key, { referencesTo } = {}) {
	const parameter = parameterBehind(project, block, block?.[key]);
	if (!parameter) return false;
	delete parameter.pdf;
	// Only when this setting is the one thing that reads it.
	const readers = referencesTo ? referencesTo(project, qualifiedName(parameter)) : null;
	if (readers && readers.length <= 1) {
		block[key] = String(parameter.value ?? '0');
		const list = project.parameters ?? [];
		const at = list.indexOf(parameter);
		if (at >= 0) list.splice(at, 1);
		return true;
	}
	return true;
}

/**
 * What else a probabilistic run varies, or could be taken to vary, besides the
 * parameters and table points it draws: for the list of what will be sampled,
 * which otherwise left a reader looking at a Weibull in a block's settings
 * and wondering where it went.
 *
 * A disruptive event at random draws its occurrences in each realisation
 * (`drawn`). A waste package's way of failing does not: it is a distribution
 * over the packages within one run -- see the note on the mode selectors
 * above -- and every realisation follows the expected curve, the fraction
 * failed by each time. Its scale and shape can be given a spread of their own
 * (`makeUncertain`), and those are then parameters, drawn like any other.
 * A block that is switched off takes no part, and is not listed.
 *
 * @returns {Array<{name: string, kind: 'event'|'waste_package', what: string, drawn: boolean}>}
 */
export function implicitInputs(project) {
	const out = [];
	const on = (b) => isEffectivelyEnabled(project, b);
	for (const e of project?.events ?? []) {
		if (timingOf(e) !== 'poisson' || e.sampled === false || !on(e)) continue;
		out.push({ name: qualifiedName(e), kind: 'event', what: describeDisruption(e), drawn: true });
	}
	for (const w of project?.waste_packages ?? []) {
		const f = failureOf(w);
		// Never failing is no law, and failing all at one time is a time: an
		// equation, which is a parameter's to vary when it names one.
		if (f === 'never' || f === 'at' || !on(w)) continue;
		const count = String(w.packages ?? '').trim();
		out.push({
			name: qualifiedName(w), kind: 'waste_package', drawn: false,
			what: `${describeFailure(w)}${count ? ` · ${count} packages` : ''}`,
		});
	}
	return out;
}
