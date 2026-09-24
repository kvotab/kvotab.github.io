/**
 * Sorting the realisations of a probabilistic run into named categories.
 *
 * A thousand realisations answer "how uncertain is the dose" as a band. The
 * question that follows is "what do the bad ones have in common", and a band
 * cannot say: it has already averaged them away. GoldSim's answer is to
 * *classify* realisations -- a category is a label and a condition over the
 * outputs ("peak dose above 1 mSv/a", "the canister fails before 10,000
 * years"), each realisation belongs to the first category whose condition it
 * meets, and every result display can then colour by category or *screen* to
 * the categories ticked. This is that, for the matrix a run keeps.
 *
 * A condition here is deliberately small: one kept series, one statistic of
 * it over the run, one comparison. That covers what the question is in
 * practice, it can be evaluated over the matrix in one pass, and it needs no
 * equation language of its own -- the model's expressions are for the model.
 *
 * **First true wins**, in the order the categories are written, and whatever
 * meets none of them is *Other*. So the order is part of the definition, as it
 * is in GoldSim, and a dialog that lets categories be reordered is not a
 * nicety.
 *
 * Nothing is stored per realisation in the model: the categories are, the
 * membership is worked out from whichever run stands, and a run that did not
 * keep the series a category reads leaves that category empty and says so.
 */

/** Which number of a series a condition reads. */
export const STATS = ['final', 'max', 'min', 'at'];

export const STAT_LABEL = {
	final: 'value at the end',
	max: 'peak',
	min: 'lowest value',
	at: 'value at a time',
};

/** How it is compared. */
export const OPS = ['>', '>=', '<', '<=', 'between'];

/**
 * Reads the categories off the model, dropping what cannot be read.
 *
 * @returns {Array<{label: string, output: string, stat: string, at: number,
 *   op: string, value: number, value2: number}>}
 */
export function categoriesOf(project) {
	const raw = project?.simulation?.categories;
	if (!Array.isArray(raw)) return [];
	return raw.map((c, i) => ({
		label: String(c?.label ?? `Category ${i + 1}`),
		output: String(c?.output ?? ''),
		stat: STATS.includes(c?.stat) ? c.stat : 'max',
		at: Number.isInteger(c?.at) ? c.at : 0,
		op: OPS.includes(c?.op) ? c.op : '>',
		value: Number(c?.value),
		value2: Number(c?.value2),
		// Screened out of every display when false. Absent means included.
		include: c?.include !== false,
	}));
}

/** What is wrong with a category, before it is used. */
export function categoryProblems(categories, outputLabels = null) {
	const out = [];
	categories.forEach((c, i) => {
		const who = c.label || `category ${i + 1}`;
		if (!c.output) out.push(`${who}: no series is named.`);
		else if (outputLabels && !outputLabels.includes(c.output)) {
			out.push(`${who}: the run did not keep ${c.output}, so nothing can be sorted by it.`);
		}
		if (!Number.isFinite(c.value)) out.push(`${who}: the value to compare against is not a number.`);
		if (c.op === 'between' && !Number.isFinite(c.value2)) {
			out.push(`${who}: 'between' needs a second value.`);
		}
	});
	return out;
}

/**
 * The one number of a realisation's series a condition reads.
 *
 * Exported because a tornado reads a design point's series the same way: the
 * peak, the end, or the value at one time.
 */
export function statisticOf(values, times, i, stat, at) {
	const from = i * times;
	if (stat === 'final') return values[from + times - 1];
	if (stat === 'at') return values[from + Math.min(times - 1, Math.max(0, at))];
	let best = NaN;
	for (let j = 0; j < times; j++) {
		const v = values[from + j];
		if (!Number.isFinite(v)) continue;
		if (Number.isNaN(best) || (stat === 'max' ? v > best : v < best)) best = v;
	}
	return best;
}

function meets(v, c) {
	if (!Number.isFinite(v)) return false;
	switch (c.op) {
		case '>': return v > c.value;
		case '>=': return v >= c.value;
		case '<': return v < c.value;
		case '<=': return v <= c.value;
		case 'between': {
			const lo = Math.min(c.value, c.value2);
			const hi = Math.max(c.value, c.value2);
			return v >= lo && v <= hi;
		}
		default: return false;
	}
}

/**
 * Which category each realisation falls in.
 *
 * @param {Array} categories   from `categoriesOf`
 * @param {object} run  `{outputs, values, times, iterations}` as a
 *   probabilistic result holds them: `values[k]` realisation-major for
 *   `outputs[k]`
 * @returns {{member: Uint16Array, counts: number[], missing: string[]}}
 *   `member[i]` is the category's position, or `categories.length` for Other;
 *   `counts` has one entry per category and one more for Other
 */
export function classify(categories, run) {
	const { outputs, values, iterations } = run;
	// A result carries its times as `t`; a caller that has only the count
	// may say `times`. Reading one and not the other made every condition
	// NaN and every category empty, in the browser and not in the test.
	const times = run.times ?? run.t?.length ?? 0;
	const member = new Uint16Array(iterations).fill(categories.length);
	const counts = new Array(categories.length + 1).fill(0);
	const missing = [];
	const column = categories.map((c) => {
		const k = outputs.findIndex((o) => o.label === c.output);
		if (k < 0 && c.output) missing.push(c.output);
		return k;
	});
	// A varied parameter is one value per realisation rather than a curve
	// (`flat`), so its peak, its end and its value at any time are that value.
	const stride = (k) => (run.flat?.[k] ? 1 : times);
	for (let i = 0; i < iterations; i++) {
		for (let c = 0; c < categories.length; c++) {
			const k = column[c];
			if (k < 0) continue;
			const v = statisticOf(values[k], stride(k), i, categories[c].stat, categories[c].at);
			if (meets(v, categories[c])) { member[i] = c; break; }
		}
		counts[member[i]]++;
	}
	return { member, counts, missing: [...new Set(missing)] };
}

/**
 * Which realisations the displays should use: 1 to keep, 0 to screen out.
 *
 * `null` when every category is included, which is the common case and the
 * one every statistic should not have to check a mask for. Other is always
 * included: it is what is left, and screening it out would need a category
 * of its own to say so.
 */
export function includeMask(categories, member) {
	if (categories.every((c) => c.include)) return null;
	const mask = new Uint8Array(member.length);
	for (let i = 0; i < member.length; i++) {
		const c = member[i];
		mask[i] = c >= categories.length || categories[c].include ? 1 : 0;
	}
	return mask;
}

/** One line saying what a category is, for a list. */
export function describeCategory(c) {
	const how = c.stat === 'at' ? `value at time #${c.at + 1}` : STAT_LABEL[c.stat] ?? c.stat;
	const cmp = c.op === 'between'
		? `between ${c.value} and ${c.value2}`
		: `${c.op} ${c.value}`;
	return `${c.output || '?'}: ${how} ${cmp}`;
}
