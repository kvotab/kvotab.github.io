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
 * inventory it is scaling. Nothing else in this tool has to know: each scheme
 * comes out of here as an *expression* in the donor's amount, the builder
 * multiplies it into the flux, and the tangent generator differentiates it the
 * way it differentiates everything else. So the Jacobian stays analytic.
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
		+ 'an element against an elemental solubility. The amount is summed over '
		+ 'the group, so the isotopic proportions of what moves are those of what '
		+ 'is there.',
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

/** Whether this scheme needs the amount summed over a group. */
export function isShared(scheme) {
	return scheme === 'shared_limit' || scheme === 'shared_langmuir';
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
	const inverted = !!scheme.unavailable;
	const body = (() => {
		if (scheme.scheme === 'limit' || scheme.scheme === 'shared_limit') {
			const limit = compile(scheme.limit);
			// `min(limit/amount, 1)`, with the empty compartment answered
			// rather than divided by.
			return `((${amount}) > 0 ? Math.min((${limit}) / (${amount}), 1) : 1)`;
		}
		// Langmuir, in the linear approximation: (amount + a) / (amount + b).
		// Rises towards 1 as the inventory grows when a < b, which is the
		// sorption case -- more material, a larger fraction in solution.
		const a = compile(scheme.top);
		const b = compile(scheme.bottom);
		return `(((${amount}) + (${b})) !== 0 ? (((${amount}) + (${a})) / ((${amount}) + (${b}))) : 1)`;
	})();
	return inverted ? `(1 - ${body})` : body;
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
