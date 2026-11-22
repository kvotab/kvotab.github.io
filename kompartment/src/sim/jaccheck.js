/**
 * Is the generated Jacobian the derivative of the generated derivative?
 *
 * `src/sim/jacobian.js` writes `df/dy` from the model's equations, and the
 * stiff solvers believe it. When it is right they take a fraction of the steps;
 * when it is wrong they do not fail loudly, they *converge to a different
 * answer* or grind. That is the worst shape a bug can have, and it is the
 * reason this exists: a run that looks fine is not evidence.
 *
 * So the matrix is compared against finite differences of the same generated
 * `dydt`. Neither is the truth — one is exact arithmetic on a possibly wrong
 * expression, the other is inexact arithmetic on the right one — but they are
 * produced by different code from the same model, so an agreement is worth
 * something and a disagreement is always worth reading.
 *
 * **Three things are checked, and the third is the one that matters most.**
 *
 *   1. Every entry the pattern declares: analytic against differenced.
 *   2. That the differenced matrix is not larger than the pattern. An entry
 *      the pattern omits is *never evaluated* by the solver, so a missing one
 *      is silently dropped from the iteration matrix — and unlike a wrong
 *      value, no amount of tightening the tolerance recovers it. This is the
 *      failure the sparsity pattern makes possible and a dense Jacobian
 *      cannot have.
 *   3. That the colouring is a colouring: two columns in one group must share
 *      no row, or the seeds collide and the values read back are sums.
 *
 * **What is compared, and what is skipped.** A difference quotient is a
 * subtraction of two nearly equal numbers, so an entry whose effect on the
 * derivative is below the rounding of that derivative tells you nothing. Such
 * an entry is *unresolvable* and is counted rather than judged: reporting it
 * as a disagreement would bury the real ones, and reporting it as agreement
 * would be a lie. On a decay chain most of the matrix is unresolvable at the
 * starting state, which is why the check is run at several states rather than
 * at one.
 *
 * **The states it runs at.** The model's own initial state first, since that is
 * the one a run actually begins from. Then states with every compartment given
 * something, at a few times: an empty compartment contributes nothing to any
 * column, and a model that starts with one nuclide in one box would otherwise
 * leave nine tenths of its matrix untested.
 */

import { Project } from '../domain/project.js';
import { cellNames } from '../domain/farfield.js';
import { buildSystem } from './builder.js';
import { describeEntry } from './runner.js';

/**
 * A name per state, in the order the state vector holds them.
 *
 * `describeEntry` does this for an ordinary block. A far-field path does not
 * fit it: its width is cells x nuclides while its `dims` name only the
 * nuclides, so walking its offsets against the index space runs off the end.
 * Its own layout says how it is laid out, and that is used instead -- a cell
 * of a path is a state like any other and deserves a name in the hover.
 *
 * Nothing here may throw: a check that cannot label one block should still
 * check the matrix.
 */
function stateLabels(layout) {
	const labels = new Array(layout.nstate);
	for (const entry of layout.states ?? []) {
		try {
			if (entry.kind === 'farfield' && entry.farf) {
				const { nnuc, otherDims, otherWidth, ncells, listName } = entry.farf;
				const names = listName ? layout.indexSpace.indexNames(listName) : [null];
				const cells = (() => {
					try { return cellNames(entry.block); } catch { return null; }
				})();
				for (let o = 0; o < otherWidth; o++) {
					const others = otherDims.length ? layout.indexSpace.tupleAt(otherDims, o) : [];
					const base = entry.base + o * ncells * nnuc;
					for (let m = 0; m < nnuc; m++) {
						const index = [];
						let k = 0;
						for (const dim of entry.dims) index.push(dim === listName ? names[m] : others[k++]);
						const suffix = index.length ? ` [${index.join(', ')}]` : '';
						for (let cell = 0; cell < ncells; cell++) {
							labels[base + cell * nnuc + m] =
								`${entry.name}${suffix} ${cells?.[cell] ?? `cell ${cell + 1}`}`;
						}
					}
				}
				continue;
			}
			for (const d of describeEntry(layout, entry, entry.kind, 'y')) labels[d.offset] = d.label;
		} catch {
			for (let i = 0; i < entry.width; i++) {
				labels[entry.base + i] = entry.width > 1
					? `${entry.name} [${i}]` : entry.name;
			}
		}
	}
	for (let i = 0; i < layout.nstate; i++) if (!labels[i]) labels[i] = `state ${i}`;
	return labels;
}

/**
 * How many columns to difference before sampling instead.
 *
 * The check costs two evaluations of the whole derivative per column. On the
 * bundled models that is nothing; on an assessment of 22,000 states it is
 * 44,000 evaluations per state checked, which is minutes. Past this many
 * columns a spread sample is taken and the report says so -- a check that is
 * never run because it takes too long is worth less than one that covers a
 * fifth of the matrix in a second.
 */
export const MANY_COLUMNS = 400;

/**
 * How many colour groups to sweep before sampling instead.
 *
 * A group costs one tangent call and one evaluation of the derivative and
 * covers every entry of every column in it, so this is the cheap pass -- but
 * on a model with sixty groups and a 22 ms derivative it is still seconds per
 * state, and there are four states.
 */
export const MANY_GROUPS = 40;

/** Relative perturbation, and the floor under it for a state at zero. */
const REL_STEP = 1e-6;

/** An entry counts as agreeing within this, relative to the larger of the two. */
const TOLERANCE = 1e-3;

/**
 * Ridders' method, for a disagreement looked at again: how many steps, how
 * much smaller each is than the one before, and when rounding is taken to
 * have won -- the tableau's diagonal moving by more than `RIDDERS_SAFE` times
 * the best error it has reached. Numerical Recipes' `dfridr`, row for row.
 */
const RIDDERS_LEVELS = 10;
const RIDDERS_SHRINK = 1.4;
const RIDDERS_SAFE = 2;

/**
 * Where each run of the tableau starts, as fractions of the check's own step.
 *
 * Ten steps shrinking by 1.4 cover a factor of twenty, and that is enough
 * where the step is a few times the scale the function bends on. It is not
 * where the step is far above it, and at an empty compartment it can be: the
 * step there is read off the largest state in the model, a millionth of an
 * inventory of 1e10, while a Langmuir availability turns over at its own
 * constant, which may be 1e-2. So the tableau is run again from starts some
 * decades down, and the estimate it is surest of is the one kept.
 */
const RIDDERS_STARTS = [1, 1e-2, 1e-4, 1e-6];

/**
 * How many columns with a disagreement are looked at again per state, worst
 * first. A column costs up to eighty evaluations of the derivative, which is
 * nothing on a bundled model and two seconds on a 55,728-state one -- where
 * fewer are taken, and a disagreement past the count is reported as the
 * single difference found it.
 */
const RIDDERS_COLUMNS = 24;
const RIDDERS_COLUMNS_LARGE = 6;

/**
 * `f(t, y)` differenced along one column.
 *
 * Central where the state is away from zero, one-sided at zero -- a
 * compartment held at zero by the non-negativity constraint has no left-hand
 * derivative to take, and stepping to `-h` there asks the model a question it
 * is not defined for.
 */
function differenceColumn(dydt, t, y, j, f0, plus, minus, out) {
	const yj = y[j];
	const scale = Math.abs(yj);
	if (scale > 0) {
		const h = REL_STEP * scale;
		y[j] = yj + h;
		dydt(t, y, plus);
		y[j] = yj - h;
		dydt(t, y, minus);
		y[j] = yj;
		for (let i = 0; i < out.length; i++) out[i] = (plus[i] - minus[i]) / (2 * h);
		return h;
	}
	// At zero: forward only, with a step read off the rest of the vector since
	// the state itself gives no scale.
	let big = 0;
	for (let i = 0; i < y.length; i++) big = Math.max(big, Math.abs(y[i]));
	const h = REL_STEP * (big > 0 ? big : 1);
	y[j] = h;
	dydt(t, y, plus);
	y[j] = yj;
	for (let i = 0; i < out.length; i++) out[i] = (plus[i] - f0[i]) / h;
	return h;
}

/**
 * One column's entries, at the rows asked for, by Ridders' method.
 *
 * A difference quotient at one step is out where the function it differences
 * bends on a scale not far above that step, however exact the generated entry
 * is: a Langmuir availability `(A + a)/(A + b)` at an empty compartment, which
 * turns over at `b`, differenced with a step read off the largest state in
 * the model. That is a disagreement in the question, not in the matrix.
 *
 * So the column is differenced again at steps shrinking by `RIDDERS_SHRINK`,
 * and each row's quotients are extrapolated to a step of nought through a
 * Neville tableau -- taking away `h`, `h^2` and on for a one-sided quotient,
 * `h^2`, `h^4` and on for a central one -- until rounding begins to grow
 * faster than the extrapolation gains. Central where the state is away from
 * zero, since a step a millionth of the state's own size never crosses it;
 * one-sided at zero, for the reason `differenceColumn` gives. Each start in
 * `RIDDERS_STARTS` runs the tableau afresh, and the estimate kept for a row
 * is the one with the smallest error the tableau reached. A start whose
 * estimates all meet the generated entries ends the search: what is being
 * asked is whether they can be met, and they have been.
 *
 * @param {Int32Array|number[]} rows   the rows of column `j` to estimate
 * @param {Float64Array} analytic      the generated entry at each of `rows`
 * @returns {Array<{value: number, err: number}>} per row; `err` is Infinity
 *   where no estimate could be made
 */
function riddersColumn(system, t, y, work, j, h0, rows, analytic, f0, plus, minus) {
	const m = rows.length;
	const oneSided = !(Math.abs(y[j]) > 0);
	const factor = oneSided ? RIDDERS_SHRINK : RIDDERS_SHRINK * RIDDERS_SHRINK;
	const best = Array.from({ length: m }, () => ({ value: NaN, err: Infinity }));
	const meets = (r) => {
		const v = best[r].value;
		if (!Number.isFinite(v)) return false;
		const size = Math.max(Math.abs(analytic[r]), Math.abs(v));
		return size === 0 || Math.abs(analytic[r] - v) <= TOLERANCE * size;
	};
	for (const start of RIDDERS_STARTS) {
		let h = h0 * start;
		if (!(h > 0)) break;
		const tableau = new Array(m).fill(null);
		const done = new Uint8Array(m);
		const value = new Float64Array(m).fill(NaN);
		const err = new Float64Array(m).fill(Infinity);
		for (let level = 0; level < RIDDERS_LEVELS; level++) {
			work[j] = y[j] + h;
			system.dydt(t, work, plus);
			if (!oneSided) {
				work[j] = y[j] - h;
				system.dydt(t, work, minus);
			}
			work[j] = y[j];
			let live = 0;
			for (let r = 0; r < m; r++) {
				if (done[r]) continue;
				const i = rows[r];
				const d = oneSided ? (plus[i] - f0[i]) / h : (plus[i] - minus[i]) / (2 * h);
				if (!Number.isFinite(d)) { done[r] = 1; continue; }
				const col = [d];
				const prev = tableau[r];
				if (prev) {
					let fac = factor;
					for (let k = 1; k <= level; k++) {
						col[k] = (col[k - 1] * fac - prev[k - 1]) / (fac - 1);
						fac *= factor;
						const e = Math.max(Math.abs(col[k] - col[k - 1]), Math.abs(col[k] - prev[k - 1]));
						if (e <= err[r]) { err[r] = e; value[r] = col[k]; }
					}
					// Rounding has taken over once the diagonal moves by more than
					// twice the best error: smaller steps only add noise from here.
					if (Math.abs(col[level] - prev[level - 1]) >= RIDDERS_SAFE * err[r]) {
						done[r] = 1;
						continue;
					}
				}
				tableau[r] = col;
				live++;
			}
			if (!live) break;
			h /= RIDDERS_SHRINK;
		}
		for (let r = 0; r < m; r++) {
			if (err[r] < best[r].err) best[r] = { value: value[r], err: err[r] };
		}
		let all = true;
		for (let r = 0; r < m && all; r++) if (!meets(r)) all = false;
		if (all) break;
	}
	return best;
}

/**
 * Which columns to scan for entries outside the pattern, and whether that is
 * all of them.
 *
 * This is the pass that costs an evaluation of the derivative *per column*, so
 * it is what bounds the check on a wide model. The group sweep above covers
 * every entry of every column it touches for one evaluation per group; this
 * one buys the question the group sweep cannot ask, one column at a time, and
 * is a spot check by nature -- four hundred columns of a 55,728-state matrix is
 * under one per cent of it however they are chosen.
 */
function columnsToCheck(n, most) {
	if (n <= most) return { columns: Array.from({ length: n }, (_, j) => j), sampled: false };
	// Spread rather than the first `most`: a model's states are laid out block
	// by block, so the first few hundred are all one compartment.
	const step = n / most;
	const out = [];
	for (let k = 0; k < most; k++) out.push(Math.min(n - 1, Math.round(k * step)));
	return { columns: [...new Set(out)], sampled: true };
}

/**
 * Which colour groups to sweep, and whether that is all of them.
 *
 * One group costs one tangent call and one evaluation of the derivative, and
 * covers every entry of every column in it -- so a sweep of all the groups
 * covers the whole matrix for about twice what forming it costs. On a model
 * with sixty groups and a 22 ms derivative that is still seconds, so a large
 * one takes a spread sample and says so.
 */
function groupsToSweep(groups, most) {
	if (!groups?.length) return { chosen: [], sampled: false };
	if (groups.length <= most) return { chosen: groups.map((_, g) => g), sampled: false };
	const step = groups.length / most;
	const out = new Set();
	for (let k = 0; k < most; k++) out.add(Math.min(groups.length - 1, Math.round(k * step)));
	return { chosen: [...out], sampled: true };
}

/**
 * One comparison, at one (t, y).
 *
 * TWO PASSES, because the two questions have different costs and only one of
 * them can use the colouring.
 *
 * **By colour group, for the values.** A group's columns share no row, so one
 * perturbation of all of them at once moves each row by the one entry of that
 * group which owns it -- which is precisely the trick a differenced Jacobian
 * uses, and precisely what `groups` is for. One evaluation of the derivative
 * then yields every entry of every column in the group, against one evaluation
 * *per column* before. On model F that is 60 evaluations where it was
 * 800, and it covers the whole matrix rather than four hundred columns of it.
 *
 * **By column, for what the pattern does not declare.** The group pass cannot
 * answer that question: it reads each row through the pattern, so an entry the
 * pattern is missing is attributed to whichever column of the group does own
 * that row. Finding a missing entry means differencing one column and scanning
 * every row of the result, which costs an evaluation per column -- so it is
 * done on a sample, and the sample is what bounds the whole check.
 *
 * The group pass uses forward differences. It never steps a state negative,
 * which matters because a model may hold a `sqrt` or a `log` of an inventory,
 * and its truncation error is about 1e-6 relative -- three orders inside the
 * 0.1% this compares at.
 */
function compareAt(system, t, y, labels, opts) {
	const n = system.layout.nstate;
	const { pattern, jvp, groups } = system.jacobian;
	const { colPtr, rowIdx } = pattern;
	// The whole matrix is never formed. The group pass reads its values through
	// `jvp`, one call per group, and the column pass is looking for entries the
	// pattern does *not* have -- where the generated value is zero by
	// definition and there is nothing to read. Forming it cost four seconds a
	// state on a 55,728-state model and was used for nothing.

	// The audit's rows are left at their diagonal on purpose for a solver that
	// iterates (see `buildJacobian` in ./jacobian.js), so what a difference
	// finds there is neither a missing entry nor a wrong one.
	const budget = system.jacobian.budgetRows === 'diagonal' ? system.layout.budget : null;
	const audit = (i) => !!budget && i >= budget.base && i < budget.base + budget.terms.length * budget.nfam;

	const f0 = new Float64Array(n);
	const plus = new Float64Array(n);
	const minus = new Float64Array(n);
	const col = new Float64Array(n);
	const analytic = new Float64Array(n);
	const seed = new Float64Array(n);
	const step = new Float64Array(n);
	const owner = new Int32Array(n);
	const work = Float64Array.from(y);
	system.dydt(t, work, f0);

	const disagreements = [];
	const outside = [];
	let checked = 0;
	let unresolvable = 0;
	let nonFinite = 0;
	let worst = null;

	// A step for column j: relative to the state, with a floor read off the
	// whole vector since a state at zero offers no scale of its own.
	let big = 0;
	for (let i = 0; i < n; i++) big = Math.max(big, Math.abs(y[i]));
	const floor = REL_STEP * (big > 0 ? big : 1);
	const stepFor = (j) => (Math.abs(y[j]) > 0 ? REL_STEP * Math.abs(y[j]) : floor);

	const judge = (i, j, a, d, h) => {
		// Can a difference see this entry at all? Its effect on row i is about
		// `entry * h`, against a derivative whose own rounding is about
		// eps*|f0[i]|. Below that the quotient is noise and says nothing.
		const effect = Math.max(Math.abs(a), Math.abs(d)) * h;
		if (!(effect > 1e-8 * Math.abs(f0[i])) || !Number.isFinite(d)) { unresolvable++; return; }
		checked++;
		const size = Math.max(Math.abs(a), Math.abs(d));
		const rel = Math.abs(a - d) / size;
		const entry = { row: i, col: j, rowLabel: labels[i], colLabel: labels[j], analytic: a, numeric: d, relative: rel };
		// The worst of those that agree; a disagreement is looked at again
		// below before it is let stand, and is the worst if it does.
		if (rel > TOLERANCE) disagreements.push(entry);
		else if (!worst || rel > worst.relative) worst = entry;
	};

	// --- pass one: every entry of the sampled colour groups ------------------
	const { chosen, sampled: groupsSampled } = groupsToSweep(groups, opts.mostGroups);
	for (const g of chosen) {
		const cols = groups[g];
		owner.fill(-1);
		seed.fill(0);
		step.fill(0);
		for (const j of cols) {
			seed[j] = 1;
			step[j] = stepFor(j);
			for (let k = colPtr[j]; k < colPtr[j + 1]; k++) owner[rowIdx[k]] = j;
		}
		// J*v for the group: with no row shared, row i holds J[i][owner[i]].
		jvp(t, y, seed, analytic);
		// An exact derivative may legitimately be infinite -- `d/dA sqrt(A)` at
		// A = 0 is -- and where it is, the solver differences this state too.
		// Saying so beats reporting every entry of the group as a disagreement.
		let finite = true;
		for (let i = 0; i < n && finite; i++) if (!Number.isFinite(analytic[i])) finite = false;
		if (!finite) { nonFinite++; opts.onProgress?.(); continue; }
		for (const j of cols) work[j] = y[j] + step[j];
		system.dydt(t, work, plus);
		for (const j of cols) work[j] = y[j];
		for (let i = 0; i < n; i++) {
			const j = owner[i];
			if (j < 0 || audit(i)) continue;
			judge(i, j, analytic[i], (plus[i] - f0[i]) / step[j], step[j]);
		}
		opts.onProgress?.();
	}

	// --- a disagreement looked at again, by Ridders' method -------------------
	// Before it is reported: one forward difference is out wherever the entry's
	// function bends on a scale near its step, and the generated entry may be
	// exact there. The tableau reaches the derivative; a matrix that is wrong
	// stays wrong, and is then reported with the tableau's value -- the nearest
	// to the derivative there is -- beside the single difference that found it.
	let refined = 0;
	let lookedAgain = 0;
	if (disagreements.length) {
		const byColumn = new Map();
		for (const d of [...disagreements].sort((p, q) => q.relative - p.relative)) {
			if (!byColumn.has(d.col)) byColumn.set(d.col, []);
			byColumn.get(d.col).push(d);
		}
		const most = n > 8000 ? RIDDERS_COLUMNS_LARGE : RIDDERS_COLUMNS;
		const standing = new Set();
		for (const [j, list] of byColumn) {
			if (lookedAgain >= most) break;
			lookedAgain++;
			const rows = list.map((d) => d.row);
			const generated = Float64Array.from(list, (d) => d.analytic);
			const est = riddersColumn(system, t, y, work, j, stepFor(j), rows, generated, f0, plus, minus);
			list.forEach((d, r) => {
				const { value, err } = est[r];
				if (!Number.isFinite(value) || !Number.isFinite(err)) return;
				const size = Math.max(Math.abs(d.analytic), Math.abs(value));
				const rel = size > 0 ? Math.abs(d.analytic - value) / size : 0;
				if (rel <= TOLERANCE) {
					refined++;
					standing.add(d);
					if (!worst || rel > worst.relative) {
						worst = { ...d, numeric: value, relative: rel, first: d.numeric };
					}
					return;
				}
				d.first = d.numeric;
				d.numeric = value;
				d.error = err;
				d.relative = rel;
			});
		}
		// Those that met the generated entry when looked at again are no longer
		// disagreements; the rest keep their place, worst first below.
		if (standing.size) {
			const kept = disagreements.filter((d) => !standing.has(d));
			disagreements.length = 0;
			disagreements.push(...kept);
		}
	}

	// --- pass two: what the pattern does not declare -------------------------
	const { columns, sampled: colsSampled } = columnsToCheck(n, opts.mostColumns);
	const inPattern = new Uint8Array(n);
	for (const j of columns) {
		// Forward, not central: this pass asks only whether there is an effect
		// here at all, judged against the same resolvability floor, and a
		// second-order term leaks in at `h` times the size of a real entry --
		// far under that floor. It halves the evaluations, which is what this
		// pass costs and the reason it is sampled at all.
		const h = stepFor(j);
		work[j] = y[j] + h;
		system.dydt(t, work, plus);
		work[j] = y[j];
		inPattern.fill(0);
		for (let k = colPtr[j]; k < colPtr[j + 1]; k++) inPattern[rowIdx[k]] = 1;
		for (let i = 0; i < n; i++) {
			if (inPattern[i] || audit(i)) continue;  // pass one judged those
			const d = (plus[i] - f0[i]) / h;
			if (!Number.isFinite(d) || d === 0) continue;
			if (!(Math.abs(d) * h > 1e-8 * Math.abs(f0[i]))) continue;
			outside.push({ row: i, col: j, rowLabel: labels[i], colLabel: labels[j], analytic: 0, numeric: d });
		}
		opts.onProgress?.();
	}

	disagreements.sort((p, q) => q.relative - p.relative);
	outside.sort((p, q) => Math.abs(q.numeric) - Math.abs(p.numeric));
	if (disagreements.length) worst = disagreements[0];
	return {
		checked,
		unresolvable,
		nonFinite,
		refined,
		lookedAgain,
		columns: columns.length,
		groups: chosen.length,
		ofGroups: groups?.length ?? 0,
		sampled: groupsSampled || colsSampled,
		worst,
		disagreements,
		outside,
		missing: outside.length,
	};
}

/**
 * Whether every group of the colouring really shares no row.
 *
 * Structural, and cheap: the colouring is what lets one evaluation of the
 * tangent fill a whole group of columns, and a group with two columns sharing
 * a row would have them add into the same entry. `colouringIsValid` in
 * jacobian.js asserts the same thing; this reports it instead.
 */
function checkColouring(pattern, groups) {
	if (!groups) return { groups: 0, clashes: [] };
	const { colPtr, rowIdx } = pattern;
	const clashes = [];
	for (let g = 0; g < groups.length; g++) {
		const seen = new Map();
		for (const j of groups[g]) {
			for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
				const i = rowIdx[k];
				if (seen.has(i)) clashes.push({ group: g, row: i, a: seen.get(i), b: j });
				else seen.set(i, j);
			}
		}
	}
	return { groups: groups.length, clashes };
}

/**
 * The states to check at.
 *
 * The model's own start, then the same vector with every compartment filled,
 * at three times across the run. Filling matters: a column whose state is zero
 * and whose row is zero everywhere contributes nothing at all, so a model
 * starting with one nuclide in one box would report a hundred per cent
 * agreement on a matrix it had barely touched.
 */
function statesToCheck(system, project) {
	const y0 = system.initialState();
	const t0 = Number(project.simulation.start_time) || 0;
	const t1 = Number(project.simulation.end_time);
	const span = Number.isFinite(t1) && t1 > t0 ? t1 - t0 : 1;
	let big = 0;
	for (const v of y0) big = Math.max(big, Math.abs(v));
	const fill = (scale, seed) => Float64Array.from(y0, (v, i) => (
		v !== 0 ? v : (big > 0 ? big : 1) * scale * (1 + ((i * 7 + seed) % 9) / 9)
	));
	const all = [
		{ label: `the model's own initial state, t = ${fmt(t0)}`, t: t0, y: Float64Array.from(y0) },
		{ label: `every compartment at 1e-3 of the largest, t = ${fmt(t0 + span * 0.01)}`, t: t0 + span * 0.01, y: fill(1e-3, 1) },
		{ label: `every compartment at 1e-6 of the largest, t = ${fmt(t0 + span * 0.25)}`, t: t0 + span * 0.25, y: fill(1e-6, 4) },
		{ label: `every compartment at 1e-9 of the largest, t = ${fmt(t0 + span * 0.9)}`, t: t0 + span * 0.9, y: fill(1e-9, 8) },
	];
	// A very large model checks at two of them rather than four: each state
	// costs a tangent call and an evaluation of the derivative per colour
	// group, which on a 55,728-state assessment is six seconds. The two kept
	// are the two that differ in kind -- the state a run actually begins from,
	// and one with every compartment carrying something.
	return system.layout.nstate > 8000 ? [all[0], all[2]] : all;
}

function fmt(v) {
	if (!Number.isFinite(v)) return String(v);
	if (v === 0) return '0';
	return Math.abs(v) >= 1e5 || Math.abs(v) < 1e-3 ? v.toExponential(2) : String(Number(v.toPrecision(6)));
}

/**
 * The picture, and nothing that costs an evaluation of the model.
 *
 * **The sparsity pattern is structural.** It is read off the equations when the
 * model is built and does not depend on the clock or on the state -- `Water`
 * reads `Regolith` at every instant of every run or at none of them. So the
 * drawing needs no time, no state and no differencing, and asking for it costs
 * the build and nothing more.
 *
 * That is worth separating from the check below, which does depend on where it
 * is asked, and which costs an evaluation of the whole model per colour group
 * and per sampled column.
 */
export function jacobianPattern(input, opts = {}) {
	const project = input instanceof Project ? input : new Project(input);
	const system = opts.system ?? buildSystem(project);
	if (!system.jacobian?.available) {
		return {
			available: false,
			reason: system.jacobian?.reason ?? 'this model has no analytic Jacobian',
		};
	}
	return {
		available: true,
		n: system.layout.nstate,
		nnz: system.jacobian.nnz,
		density: system.jacobian.density,
		colours: system.jacobian.colours,
		constant: !!system.jacobian.constant,
		labels: stateLabels(system.layout),
		pattern: {
			colPtr: Array.from(system.jacobian.pattern.colPtr),
			rowIdx: Array.from(system.jacobian.pattern.rowIdx),
			nnz: system.jacobian.pattern.nnz,
		},
	};
}

/**
 * Checks a model's generated Jacobian against finite differences.
 *
 * **Where it is checked.** Not at one point, and not only at the start. The
 * values of `df/dy` depend on `(t, y)` where the pattern does not, so the
 * comparison is made at the model's own initial state and then at three states
 * with every compartment given something, spread across the run. An empty
 * compartment contributes nothing to any column, so a model that begins with
 * one nuclide in one box would otherwise report a clean bill on a matrix it
 * had barely touched. `statesToCheck` is where those are chosen.
 *
 * @param {object|Project} input
 * @param {object} [opts]
 * @param {object} [opts.system]       a system already built
 * @param {number} [opts.mostColumns]  columns to scan for entries outside the pattern
 * @param {number} [opts.mostGroups]   colour groups to sweep for values
 * @param {(done: number, total: number) => void} [opts.onProgress]
 * @returns {object} the report the interface renders
 */
export function checkJacobian(input, opts = {}) {
	const project = input instanceof Project ? input : new Project(input);
	const system = opts.system ?? buildSystem(project);
	const drawn = jacobianPattern(project, { system });
	if (!drawn.available) return drawn;

	const labels = drawn.labels;
	// Four hundred columns is two hundred evaluations of the derivative per
	// state, which is a fifth of a second on a bundled example and twenty
	// seconds on a 55,728-state assessment. The count comes down with the
	// model's size so that the check stays something somebody will actually
	// wait for; the report says when it has been cut.
	const mostColumns = opts.mostColumns
		?? (system.layout.nstate > 8000 ? Math.round(MANY_COLUMNS / 4) : MANY_COLUMNS);
	const mostGroups = opts.mostGroups ?? MANY_GROUPS;
	const where = statesToCheck(system, project);

	// Enough to drive a progress bar: one tick per group and per column, at
	// every state. A check that takes half a minute on a real assessment has to
	// say how far along it is.
	const perState = Math.min(mostGroups, system.jacobian.groups?.length ?? 0)
		+ Math.min(mostColumns, system.layout.nstate);
	let done = 0;
	const tick = opts.onProgress ? () => { opts.onProgress(++done, where.length * perState); } : null;

	const at = where.map((s) => ({
		label: s.label,
		...compareAt(system, s.t, s.y, labels, { mostColumns, mostGroups, onProgress: tick }),
	}));

	const colouring = checkColouring(system.jacobian.pattern, system.jacobian.groups);
	const disagreements = at.reduce((a, c) => a + c.disagreements.length, 0);
	const missing = at.reduce((a, c) => a + c.missing, 0);

	return {
		...drawn,
		at,
		colouring,
		// The headline, worst first. An entry the pattern is missing is worse
		// than one whose value is out, because no tolerance recovers it; a
		// colouring that is not a colouring is worse still, since then every
		// value read back through it is a sum of the columns that collided.
		verdict: colouring.clashes.length ? 'colouring'
			: missing ? 'missing'
				: disagreements ? 'differs' : 'agrees',
		disagreements,
		missing,
		sampled: at.some((c) => c.sampled),
	};
}
