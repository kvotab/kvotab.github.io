/**
 * The mass-balance audit: does the model's bookkeeping close?
 *
 * Every derivative the builder emits moves an amount from somewhere to
 * somewhere: out of a compartment and into another, in from outside, out to
 * outside, away by decay, in by ingrowth, or wherever an explicit dy/dt term
 * says. With the audit on, the builder appends *budget states* to the vector,
 * one per family (a radionuclide, or "not by nuclide" for a compartment that
 * is not indexed by one) and per kind of movement, and adds every such term to
 * the matching budget as it is emitted. The budgets are integrated by the
 * solver with everything else, so at every output time
 *
 *     Σ inventory(t) − Σ inventory(0)
 *         = in − out − decay + ingrowth + explicit + between
 *
 * should hold to within the solver's tolerance -- the methods are linear in
 * the state, so the numerical solution of the sum is the sum of the numerical
 * solutions: exactly, to round-off, for the explicit solvers, and to the
 * tolerance the Newton iteration stops at for the implicit ones, which is
 * where 10^-7 relative comes from under ndf at rtol 10^-6 -- and a residual
 * that is not of that order is a finding: a state "cannot go negative" held at
 * zero (the projection puts mass back that the equations took away), or a term
 * the emission forgot. GoldSim ships a mass-balance check for its Cell
 * Pathways; this is that for compartments.
 *
 * It is not a conservation law. In becquerels the total is not conserved --
 * decay changes activity by the ratio of half-lives -- and the audit does not
 * pretend otherwise: it checks that what was added and removed accounts for
 * what is there, whatever the unit.
 */

/** The kinds of movement, in the order the budget states are laid out. */
export const TERMS = ['in', 'out', 'decay', 'ingrowth', 'explicit', 'between'];

/** How each reads in a report. */
export const TERM_LABEL = {
	in: 'in from outside',
	out: 'out to outside',
	decay: 'lost to decay',
	ingrowth: 'gained by ingrowth',
	explicit: 'by explicit dy/dt terms',
	between: 'moved in from other families',
};

/** The name of the family a compartment not indexed by nuclide belongs to. */
export const UNINDEXED = 'not by nuclide';

/** The state holding one term of one family's budget. */
export function budgetIndex(budget, term, family) {
	return budget.base + TERMS.indexOf(term) * budget.nfam + family;
}

/**
 * Above this relative residual the audit is reported as not closing. A
 * multiple of the relative tolerance, because that is what an implicit
 * solver's Newton iteration leaves behind; a hold is orders of magnitude
 * above it, not a factor.
 */
export function closedBelow(rtol) {
	const r = Number(rtol);
	return Math.max(1e-10, 20 * (Number.isFinite(r) && r > 0 ? r : 1e-6));
}

/**
 * The closure, family by family and in total.
 *
 * @param {object} budget  `layout.budget` from the builder: `base`, `nfam`,
 *   `families` (names), `members` (`{name, base, width, famOf}` per
 *   compartment, `famOf` the family of each offset)
 * @param {ArrayLike<number>} t  the output times
 * @param {ArrayLike<ArrayLike<number>>} y  the states at each: `y[i][state]`
 * @param {{rtol?: number}} [opts]  the run's relative tolerance, which sets
 *   what counts as closed
 * @returns {{
 *   worst: number,
 *   at: number,
 *   families: Array<{name: string, idle: boolean, scale: number, worst: number,
 *     relative: number, at: number, final: object}>,
 *   total: {scale: number, worst: number, relative: number, at: number, final: object},
 * }}
 */
export function audit(budget, t, y, { rtol } = {}) {
	const n = t.length;
	const F = budget.nfam;
	const inventory = Array.from({ length: F }, () => new Float64Array(n));
	for (let i = 0; i < n; i++) {
		const yi = y[i];
		for (const m of budget.members) {
			for (let off = 0; off < m.width; off++) inventory[m.famOf[off]][i] += yi[m.base + off];
		}
	}

	const rowAt = (i, f) => {
		const term = (name) => y[i][budgetIndex(budget, name, f)];
		const row = {
			inventory: inventory[f][i], start: inventory[f][0],
			in: term('in'), out: term('out'), decay: term('decay'),
			ingrowth: term('ingrowth'), explicit: term('explicit'), between: term('between'),
		};
		row.expected = row.start + row.in - row.out - row.decay + row.ingrowth + row.explicit + row.between;
		row.residual = row.inventory - row.expected;
		return row;
	};
	const addRows = (a, b) => {
		const out = {};
		for (const k of Object.keys(a)) out[k] = a[k] + b[k];
		return out;
	};
	// The scale a residual is judged against: the largest amount the family
	// ever held or moved. A residual of 1 is nothing against a gigabecquerel
	// and everything against a compartment that never held more than 2.
	const scaleOf = (row, scale) => Math.max(scale, Math.abs(row.inventory), Math.abs(row.start),
		row.in, row.out, row.decay, row.ingrowth, Math.abs(row.explicit), Math.abs(row.between));

	const families = [];
	const totals = [];
	for (let f = 0; f < F; f++) {
		let worst = 0;
		let at = t[0];
		let scale = 0;
		let last = null;
		for (let i = 0; i < n; i++) {
			const row = rowAt(i, f);
			scale = scaleOf(row, scale);
			if (Math.abs(row.residual) > worst) { worst = Math.abs(row.residual); at = t[i]; }
			last = row;
			totals[i] = totals[i] ? addRows(totals[i], row) : row;
		}
		const idle = scale === 0;
		families.push({
			name: budget.families[f], idle, scale,
			worst: idle ? 0 : worst, relative: idle ? 0 : worst / scale, at, final: last,
		});
	}

	let total = { scale: 0, worst: 0, relative: 0, at: t[0], final: null };
	for (let i = 0; i < n; i++) {
		const row = totals[i];
		if (!row) continue;
		total.scale = scaleOf(row, total.scale);
		if (Math.abs(row.residual) > total.worst) { total.worst = Math.abs(row.residual); total.at = t[i]; }
		total.final = row;
	}
	total.relative = total.scale > 0 ? total.worst / total.scale : 0;

	const live = families.filter((f) => !f.idle);
	const worstFamily = live.reduce((w, f) => (f.relative > (w?.relative ?? -1) ? f : w), null);
	return {
		worst: worstFamily?.relative ?? 0,
		at: worstFamily?.at ?? t[0],
		worstFamily: worstFamily?.name ?? null,
		closed: (worstFamily?.relative ?? 0) <= closedBelow(rtol),
		tolerance: closedBelow(rtol),
		families,
		total,
	};
}

/** A number as the report writes it. */
const num = (v) => (v === 0 ? '0' : Math.abs(v) >= 1e-3 && Math.abs(v) < 1e6
	? Number(v.toPrecision(4)).toString() : v.toExponential(3));

/** One line per family, and a first line saying whether it closes. */
export function describeAudit(a, { timeUnit = '' } = {}) {
	const unit = timeUnit ? ` ${timeUnit}` : '';
	const out = [];
	if (a.closed) {
		out.push(`mass balance: closes — worst relative residual ${a.worst.toExponential(1)}`
			+ (a.worstFamily ? ` (${a.worstFamily} at t = ${num(a.at)}${unit})` : ''));
	} else {
		out.push(`mass balance: DOES NOT CLOSE — relative residual ${a.worst.toExponential(2)} in `
			+ `${a.worstFamily} at t = ${num(a.at)}${unit}; a state held at zero, or an amount `
			+ 'the equations moved that nothing accounts for');
	}
	for (const f of a.families) {
		if (f.idle) { out.push(`  ${f.name}: nothing held or moved`); continue; }
		const r = f.final;
		const parts = [`start ${num(r.start)}`, `+ in ${num(r.in)}`, `− out ${num(r.out)}`,
			`− decay ${num(r.decay)}`, `+ ingrowth ${num(r.ingrowth)}`];
		if (r.explicit !== 0) parts.push(`${r.explicit < 0 ? '−' : '+'} explicit ${num(Math.abs(r.explicit))}`);
		if (r.between !== 0) parts.push(`${r.between < 0 ? '−' : '+'} between ${num(Math.abs(r.between))}`);
		out.push(`  ${f.name}: holds ${num(r.inventory)} at the end = ${parts.join(' ')}; `
			+ `residual ${num(r.residual)} (${f.relative.toExponential(1)} relative, worst at t = ${num(f.at)}${unit})`);
	}
	return out;
}
