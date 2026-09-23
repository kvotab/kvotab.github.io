/**
 * How much of what is in a compartment is actually available to move.
 *
 * A transfer's flux is `rate × amount[donor]`, and that is linear in the
 * inventory -- which is right for advection and diffusion and wrong for the two
 * things a near field is mostly about. Past a solubility limit the excess is
 * precipitate and does not travel in the water. Under a sorption isotherm the
 * fraction in solution *rises* with the inventory rather than staying fixed.
 * Both are the same shape of correction, and AMBER gives it a name and a place:
 *
 *     TransferFlux = TransferRate × Availability × Amount[donor]
 *
 * with `Availability` between 0 and 1 (Reference Manual §9.15).
 *
 * **It belongs to the transfer, not to the compartment**, and the manual gives
 * the reason plainly: "different transfers might have different availabilities
 * for the same compartment (e.g. if one acts through the aqueous phase and the
 * other on the total, as in erosion)". A solubility limit holds back what
 * leaches; it does not hold back what erodes. A flag on the compartment cannot
 * say that.
 *
 * Four schemes, each of which may also be inverted -- the *unavailability*
 * form, which is one minus the availability, for the transfer that carries
 * precisely what the other one leaves behind.
 *
 * **This makes the equations non-linear**, because the availability reads the
 * inventory it is scaling. Each scheme comes out of here twice: as an
 * *expression* in the donor's amount (`expressionOf`), which the builder folds
 * into the transfer's own value -- rate × availability -- and as that
 * expression's *tangent* (`tangentOf`), which the Jacobian generator folds into
 * the tangent of the same value. So the flux is still `donor × value` wherever
 * it is assembled, `T * donor` in an equation is still the flux through `T`,
 * and the Jacobian stays analytic. The limit and the two Langmuir coefficients
 * are equations with slots of their own (`OPERANDS`), differentiated like any
 * other.
 */

/** The schemes, as a model spells them. */
export const SCHEMES = ['limit', 'shared_limit', 'langmuir', 'shared_langmuir'];

/** What each is called where somebody reads it. */
export const SCHEME_LABEL = {
	limit: 'Solubility limit',
	shared_limit: 'Shared solubility limit',
	langmuir: 'Langmuir sorption',
	shared_langmuir: 'Shared Langmuir sorption',
};

/** A line each, for the panel that offers them. */
export const SCHEME_BLURB = {
	limit: 'Only as much as the limit can travel; the excess is precipitate and '
		+ 'stays behind. Availability = min(limit ÷ amount, 1).',
	shared_limit: 'The same, with one limit shared over a group — the isotopes of '
		+ 'an element against an elemental solubility, when it is shared over '
		+ 'Elements. The amount is summed over the group, so the isotopic '
		+ 'proportions of what moves are those of what is there.',
	langmuir: 'A sorption isotherm: the fraction free to move rises with the '
		+ 'inventory rather than staying fixed. Availability = (amount + α) ÷ '
		+ '(amount + β), the linear approximation AMBER uses.',
	shared_langmuir: 'The same, over a group.',
};

/** Whether a transfer has one at all. */
export function schemeOf(transfer) {
	const a = transfer?.availability;
	if (!a || !SCHEMES.includes(a.scheme)) return null;
	return a;
}

/**
 * Whether this scheme needs the amount summed over a group.
 *
 * What the group is comes from `over`, read against the donor's dimensions by
 * the builder (`availabilityTerms` in ../sim/builder.js):
 *
 *   one of the donor's own lists   the whole of it is one group -- one limit
 *                                  shared by every nuclide the donor holds
 *   a grouping of one of them      one group per index of the grouping -- over
 *                                  `Elements`, the isotopes of each element
 *                                  share that element's limit, which is what
 *                                  an elemental solubility is
 *
 * Anything else is refused by name rather than quietly read as the individual
 * scheme, which is what an unrecognised list used to come to.
 */
export function isShared(scheme) {
	return scheme === 'shared_limit' || scheme === 'shared_langmuir';
}

/**
 * The equations a scheme reads beside the amount, in the order they get slots.
 *
 * Each is an ordinary equation of the transfer's -- a parameter, an expression,
 * something time-dependent -- and the builder gives it an algebraic slot of the
 * transfer's own dimensions, named `<transfer>#<key>`, so that it is worked out
 * once per call and differentiated like everything else.
 */
export function operandKeys(scheme) {
	if (!scheme) return [];
	return scheme.scheme === 'limit' || scheme.scheme === 'shared_limit' ? ['limit'] : ['top', 'bottom'];
}

/**
 * What a shared scheme adds up.
 *
 *   amount  the inventories as the model holds them -- becquerels, usually
 *   moles   each inventory converted to moles first, through its half-life
 *
 * An elemental solubility is a statement about *atoms* in solution, and the
 * isotopes of one element share it in proportion to how many atoms of each
 * there are. In becquerels they do not: at equal activity U-238 is 18,000
 * times the atoms of U-234, and a limit shared by activity would hold the
 * U-234 back as hard as the U-238. GoldSim shares "based on the isotopic molar
 * ratios", which is right, and this is that. A model whose decay unit is
 * already `mol` gains nothing from it, and says so.
 */
export const BASES = ['amount', 'moles'];

export const BASIS_LABEL = {
	amount: 'the amounts as the model holds them',
	moles: 'moles, converted through each isotope’s half-life',
};

/** The basis a shared scheme uses, `amount` unless it says `moles`. */
export function basisOf(scheme) {
	return scheme?.basis === 'moles' ? 'moles' : 'amount';
}

/** Avogadro's number, for turning atoms into moles. */
export const AVOGADRO = 6.02214076e23;

/**
 * Moles per unit of inventory for one isotope, in the model's units.
 *
 * Becquerels are decays per second, so the atoms behind an activity A are
 * A/λ with λ in 1/s, and the moles those atoms make are that over Avogadro's
 * number. `lambdaPerTimeUnit` is what the model already holds for the
 * isotope; `secondsPerTimeUnit` carries it to 1/s.
 *
 * A stable isotope has no activity to convert -- its becquerels are zero
 * whatever it weighs -- and returns 0, so a group that carries one shares over
 * the isotopes that can be counted. In `mol` the factor is 1 by definition.
 *
 * @returns {number} moles per unit of the inventory
 */
export function molesPerUnit(decayUnit, lambdaPerTimeUnit, secondsPerTimeUnit) {
	if (decayUnit === 'mol') return 1;
	const perSecond = lambdaPerTimeUnit / secondsPerTimeUnit;
	if (!(perSecond > 0)) return 0;
	return 1 / (perSecond * AVOGADRO);
}

/**
 * The availability as an expression in `amount`.
 *
 * `amount` is whatever the caller wants to call the donor's inventory -- for
 * the builder that is an index into the state vector, and for a preview it is
 * a variable. The limit and the two Langmuir coefficients are equations in
 * their own right, so they arrive as text and are dropped in as written: they
 * may be parameters, they may be time-dependent, and the compiler resolves
 * them exactly as it resolves anything else in a rate.
 *
 * The guards are AMBER's, and each of them is a real case rather than defensive
 * noise:
 *
 *   - an amount at or below zero is fully available, because a compartment that
 *     holds nothing has nothing held back, and `limit/0` is not a number;
 *   - a limit at or below zero is an error, caught before the run by
 *     `availabilityProblems` -- it would make the availability negative, which
 *     is a flux running backwards up its own transfer.
 *
 * @param {object} scheme   from `schemeOf`
 * @param {string} amount   an expression for the donor's amount
 * @param {(text: string) => string} compile  turns one of the model's
 *   expressions into inflow: the caller knows how to resolve a name
 * @returns {string} an expression between 0 and 1
 */
export function expressionFor(scheme, amount, compile) {
	const operands = {};
	for (const key of operandKeys(scheme)) operands[key] = compile(scheme[key]);
	return expressionOf(scheme, amount, operands);
}

/**
 * The availability as an expression, given its operands already compiled.
 *
 * `operands` holds an expression per `operandKeys` entry -- in the builder the
 * slots `X[...]` those equations were worked out into. `amount` should be
 * something cheap to repeat, a local or a slot, since it appears more than
 * once.
 */
export function expressionOf(scheme, amount, operands) {
	const inverted = !!scheme.unavailable;
	const body = (() => {
		if (scheme.scheme === 'limit' || scheme.scheme === 'shared_limit') {
			// `min(limit/amount, 1)`, with the empty compartment answered
			// rather than divided by.
			return `((${amount}) > 0 ? Math.min((${operands.limit}) / (${amount}), 1) : 1)`;
		}
		// Langmuir, in the linear approximation: (amount + a) / (amount + b).
		// Rises towards 1 as the inventory grows when a < b, which is the
		// sorption case -- more material, a larger fraction in solution.
		const a = operands.top;
		const b = operands.bottom;
		return `(((${amount}) + (${b})) !== 0 ? (((${amount}) + (${a})) / ((${amount}) + (${b}))) : 1)`;
	})();
	return inverted ? `(1 - ${body})` : body;
}

/**
 * The tangent of `expressionOf` along whatever direction the caller is taking
 * it: `dAmount` and each `dOperands[key]` are the tangents of the amount and of
 * the operands, or null where one is structurally zero. Null back when the
 * whole tangent is.
 *
 * Differentiated as the code is written, branch by branch, which is the only
 * derivative a Newton iteration can use:
 *
 *   limit      1 where nothing is held back, so 0; L/a past the limit, so
 *              (dL·a − L·da)/a². At L = a exactly `Math.min` takes the 1, and so
 *              does this.
 *   Langmuir   the quotient rule on (a + α)/(a + β); 0 on the guard.
 *   held back  the same with its sign turned over.
 *
 * Past a limit the two halves of `donor × L/a × rate` meet: for an individual
 * limit the donor and the amount are the same inventory, their tangents
 * cancel, and the flux is L × rate whatever the inventory -- which is the
 * point of a solubility limit, and what the Jacobian has to say.
 */
export function tangentOf(scheme, amount, dAmount, operands, dOperands = {}) {
	const inverted = !!scheme.unavailable;
	const body = (() => {
		if (scheme.scheme === 'limit' || scheme.scheme === 'shared_limit') {
			const L = operands.limit;
			const dL = dOperands.limit ?? null;
			if (dL == null && dAmount == null) return null;
			const top = [
				dL != null ? `(${dL}) * (${amount})` : null,
				dAmount != null ? `(${L}) * (${dAmount})` : null,
			];
			const num = top[0] && top[1] ? `${top[0]} - ${top[1]}` : (top[0] ?? `-${top[1]}`);
			return `((${amount}) > 0 && (${L}) < (${amount}) ? (${num}) / ((${amount}) * (${amount})) : 0)`;
		}
		const a = operands.top;
		const b = operands.bottom;
		const da = dOperands.top ?? null;
		const db = dOperands.bottom ?? null;
		if (dAmount == null && da == null && db == null) return null;
		const sum = (...xs) => {
			const live = xs.filter((x) => x != null);
			return live.length ? `(${live.join(' + ')})` : null;
		};
		const dTop = sum(dAmount, da);
		const dBottom = sum(dAmount, db);
		const bottom = `((${amount}) + (${b}))`;
		const parts = [
			dTop != null ? `${dTop} * ${bottom}` : null,
			dBottom != null ? `((${amount}) + (${a})) * ${dBottom}` : null,
		];
		const num = parts[0] && parts[1] ? `${parts[0]} - ${parts[1]}` : (parts[0] ?? `-${parts[1]}`);
		return `(${bottom} !== 0 ? (${num}) / (${bottom} * ${bottom}) : 0)`;
	})();
	if (body == null) return null;
	return inverted ? `(-${body})` : body;
}

/**
 * What is wrong with a transfer's availability, before the run.
 *
 * Errors rather than warnings: an availability that cannot be worked out is a
 * flux that cannot be worked out, and a model that ran anyway would be
 * reporting a number nobody could account for.
 *
 * @returns {Array<{name: string, field: string, message: string}>}
 */
export function availabilityProblems(project) {
	const out = [];
	for (const t of project?.transfers ?? []) {
		const a = schemeOf(t);
		if (!a) {
			if (t.availability && t.availability.scheme) {
				out.push({
					name: t.name, field: 'availability',
					message: `'${t.availability.scheme}' is not an availability scheme `
						+ `(${SCHEMES.join(', ')}).`,
				});
			}
			continue;
		}
		if (!t.from) {
			out.push({
				name: t.name, field: 'availability',
				message: 'An availability scales what is in the donor compartment, and '
					+ 'this transfer has none — it carries an absolute flux from outside '
					+ 'the model.',
			});
			continue;
		}
		if (t.multiply_by_donor === false) {
			out.push({
				name: t.name, field: 'availability',
				message: 'This transfer is an absolute flux rather than a rate times the '
					+ 'donor, so there is no inventory for an availability to be a '
					+ 'fraction of.',
			});
			continue;
		}
		if (a.scheme === 'limit' || a.scheme === 'shared_limit') {
			if (!String(a.limit ?? '').trim()) {
				out.push({
					name: t.name, field: 'availability',
					message: 'A solubility limit scheme needs a limit: how much may travel, '
						+ 'as a number or an equation.',
				});
			}
		} else {
			for (const [key, what] of [['top', 'α, the top'], ['bottom', 'β, the bottom']]) {
				if (!String(a[key] ?? '').trim()) {
					out.push({
						name: t.name, field: 'availability',
						message: `A Langmuir scheme needs ${what} of (amount + α) ÷ (amount + β).`,
					});
				}
			}
		}
		if (isShared(a.scheme) && !String(a.over ?? '').trim()) {
			out.push({
				name: t.name, field: 'availability',
				message: 'A shared scheme needs the index list the amount is summed over — '
					+ 'the isotopes of an element share an elemental solubility, so that '
					+ 'is the radionuclide list.',
			});
		}
		if (a.basis != null && !BASES.includes(a.basis)) {
			out.push({
				name: t.name, field: 'availability',
				message: `'${a.basis}' is not a basis for the shared amount (${BASES.join(', ')}).`,
			});
		}
	}
	return out;
}

/** One line saying what a transfer's availability does, for the panel. */
export function describe(transfer) {
	const a = schemeOf(transfer);
	if (!a) return '';
	const what = SCHEME_LABEL[a.scheme] ?? a.scheme;
	const over = isShared(a.scheme) && a.over
		? ` over ${a.over}${basisOf(a) === 'moles' ? ' in moles' : ''}` : '';
	return `${a.unavailable ? `Everything ${what.toLowerCase()} holds back` : what}${over}`;
}
