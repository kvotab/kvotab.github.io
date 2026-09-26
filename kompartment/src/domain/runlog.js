/**
 * The run log: what a run was, in words that survive it.
 *
 * GoldSim writes one after every simulation -- program version, date, the
 * settings, every warning -- and calls it an audit trail, because that is what
 * it is for: six months later somebody asks which solver, which tolerance,
 * which output grid, whether anything was held at zero, and the status line
 * that answered those questions was replaced by the next run's. This is that
 * record, assembled from what the run already reported, kept with the results
 * and written into a results archive so a saved run carries its own account.
 *
 * Text, not structure: a log is read by a person, pasted into a report, or
 * diffed against last year's. The numbers in it are the numbers the footer
 * shows, formatted the same way, so the two never disagree.
 */

import { describeAudit } from './massbalance.js';
import { inventoryUnit } from './units.js';

/**
 * One line per setting, in the order somebody reads them.
 *
 * The decay unit is the model's rather than the simulation's -- it lives at the
 * top of the file, beside the nuclides -- and was read from the simulation, so
 * no log ever said it. It is always one of the two, `Bq` when unset.
 */
function settingsLines(sim = {}, project = null) {
	const out = [];
	const put = (label, v) => { if (v != null && v !== '') out.push(`  ${label}: ${v}`); };
	put('time unit', sim.time_unit);
	put('span', `${sim.start_time} – ${sim.end_time}`);
	put('output times', sim.spacing === 'series'
		? 'a series of the model’s own'
		: `${sim.output_points ?? '?'}, ${sim.spacing ?? 'log'}`);
	put('solver', sim.solver);
	put('relative tolerance', sim.rtol);
	put('absolute tolerance', sim.abstol);
	put('cannot go negative', sim.non_negative === false ? 'off everywhere' : 'per compartment');
	if (sim.mass_balance) put('mass-balance audit', 'on');
	if (sim.auto_abstol) put('tolerance follows the solution', 'each component\u2019s absolute tolerance rises with it');
	put('decay unit', inventoryUnit(project ?? sim));
	if (Number(sim.decay_ceiling) > 0) put('decay chains stop above', `${sim.decay_ceiling} years`);
	return out;
}

/**
 * The log of a deterministic run.
 *
 * @param {object} o
 * @param {object} o.project   the raw model
 * @param {object} o.payload   what the worker reported: stats, timing, jacobian,
 *   heldAtZero, stateCount, outputs
 * @param {object|null} [o.replayed]  when the run is one realisation replayed
 * @param {string} [o.build]   the program's build stamp
 * @param {Date} [o.at]        when; the caller's clock
 * @returns {string[]} lines
 */
export function runLogLines({ project, payload, replayed = null, build = '', at = new Date() }) {
	const s = payload?.stats ?? {};
	const t = payload?.timing ?? {};
	const out = [];
	out.push(`Kompartment run log${build ? ` — build ${build}` : ''}`);
	out.push(`${at.toISOString()}`);
	out.push(`model: ${project?.name ?? 'Untitled'}`);
	if (project?.description) out.push(`  ${String(project.description).replace(/\s+/g, ' ').slice(0, 200)}`);
	out.push('');
	out.push('settings');
	out.push(...settingsLines(project?.simulation, project));
	out.push('');
	if (replayed) {
		out.push(replayed.tornado
			? `this is design point ${replayed.index + 1} of ${replayed.iterations} of a tornado`
			: `this is realisation ${replayed.index + 1} of ${replayed.iterations}, seed ${replayed.seed}`);
		for (const v of replayed.values ?? []) {
			out.push(`  ${v.name} = ${Number.isFinite(v.value) ? v.value : '—'}${v.held ? ' (held)' : ''}`);
		}
		out.push('');
	}
	out.push('run');
	if (s.integrated === false) {
		out.push('  nothing integrated: no compartments, the algebraic blocks over the output grid');
	} else {
		out.push(`  states: ${payload?.stateCount ?? '?'}`);
		out.push(`  steps: ${s.nsteps ?? '?'}, rejected: ${s.nfailed ?? 0}, f evaluations: ${s.nfevals ?? '?'}`);
		if (s.nbelowtol) out.push(`  steps taken below tolerance: ${s.nbelowtol}`);
		if (s.events != null) out.push(`  events: ${s.events}, restarts: ${s.restarts ?? 0}`);
		if (s.jumps != null) out.push(`  jumps: ${s.jumps} — package failures at a time and disruptive events, applied to the state at their corners`);
		const j = payload?.jacobian;
		if (j) {
			out.push(j.available
				? `  df/dy: analytic, ${j.sparse ? 'sparse' : 'dense'}${j.colours ? `, ${j.colours} colours` : ''}${j.constant ? ', constant' : ''}`
				: `  df/dy: differenced${j.reason ? ` — ${j.reason}` : ''}`);
		}
	}
	const split = s.split;
	if (split?.used) {
		out.push(`  split: ${split.parts ?? split.jobs.length} independent parts on ${split.workers} cores (${split.mode}) — ${split.why}`);
		// One line per core: the parts it was given, solved together.
		for (const j of split.jobs) {
			out.push(`    ${j.materials.join(', ')}: ${j.states} states, ${j.nsteps ?? '?'} steps, `
				+ `compile ${Number(j.buildMs ?? 0).toFixed(1)} ms, solve ${Number(j.solveMs ?? 0).toFixed(0)} ms`);
		}
		if (split.gain) out.push(`    about ${split.gain.toFixed(1)}× a whole solve, by this machine's estimate`);
	} else if (split) {
		out.push(`  not split (${split.mode}): ${split.why}`);
	}
	out.push(`  output points: ${payload?.t?.length ?? '?'}`);
	out.push(`  series: ${payload?.outputs?.length ?? '?'}`);
	out.push(`  compile: ${Number(t.buildMs ?? 0).toFixed(1)} ms, solve: ${t.reused ? 'not repeated (states reused)' : `${Number(t.solveMs ?? 0).toFixed(0)} ms`}`);
	const held = payload?.heldAtZero ?? [];
	if (held.length) {
		out.push('');
		out.push(`held at zero: ${held.length} state${held.length === 1 ? '' : 's'} the model pushed below zero`);
		for (const h of held.slice(0, 20)) {
			out.push(`  ${h.label}: ${h.steps} steps, ${(100 * h.fraction).toFixed(1)}% of the run`);
		}
		if (held.length > 20) out.push(`  and ${held.length - 20} more`);
	}
	// A far-field path worked out semi-analytically whose unit response missed
	// its mass balance: the run went on with it, and the log says so.
	const farfield = s.farfield ?? [];
	if (farfield.length) {
		out.push('');
		out.push(`semi-analytical far-field paths: ${farfield.length} unit response`
			+ `${farfield.length === 1 ? '' : 's'} missed ${farfield.length === 1 ? 'its' : 'their'} mass balance`);
		for (const w of farfield) out.push(`  ${w.block}: ${w.message}`);
	}
	if (payload?.massBalance) {
		out.push('');
		out.push(...describeAudit(payload.massBalance, { timeUnit: project?.simulation?.time_unit ?? '' }));
	}
	return out;
}

/**
 * The scenarios run beside the selected one, appended under its log: which,
 * and what each run came to. The lines above are the selected scenario's.
 *
 * @param {string|null} active  the selected scenario
 * @param {Array<{name: string, r?: object|null, error?: string|null, running?: boolean,
 *   queued?: boolean}>} runs  the others, in the model's order
 */
export function scenarioLogLines(active, runs) {
	if (!runs?.length) return [];
	const out = ['', 'scenarios run together'];
	out.push(`  ${active} — the selected scenario, the run described above`);
	for (const e of runs) {
		if (e.error) { out.push(`  ${e.name} — did not run: ${e.error}`); continue; }
		if (e.running || e.queued) { out.push(`  ${e.name} — still running`); continue; }
		const s = e.r?.stats ?? {};
		const t = e.r?.timing ?? {};
		out.push(e.r
			? `  ${e.name} — ${s.nsteps ?? '?'} steps, compile ${Number(t.buildMs ?? 0).toFixed(1)} ms, `
				+ `solve ${t.reused ? 'not repeated (states reused)' : `${Number(t.solveMs ?? 0).toFixed(0)} ms`}`
				+ (s.split?.used ? `, in ${s.split.parts ?? s.split.jobs.length} parts on ${s.split.workers} cores` : '')
			: `  ${e.name} — not run yet`);
	}
	return out;
}

/**
 * The log of a probabilistic run, appended under the deterministic one when
 * both stand.
 */
export function probabilisticLogLines(prob) {
	if (!prob) return [];
	const s = prob.stats ?? {};
	const out = [''];
	out.push(s.tornado ? 'tornado' : 'probabilistic run');
	out.push(`  ${s.tornado ? 'design points' : 'realisations'}: ${prob.iterations}`);
	if (!s.tornado) {
		out.push(`  seed: ${s.seed}, sampling: ${s.latin === false ? 'independent draws' : 'Latin hypercube'}`);
	} else {
		out.push(`  swung to the ${Math.round(s.tornado.low * 100)}th and ${Math.round(s.tornado.high * 100)}th percentiles`);
	}
	out.push(`  sampled inputs: ${s.sampled ?? prob.plan?.length ?? '?'}`);
	if (s.correlated) out.push(`  correlated inputs: ${s.correlated}${s.correlationAdjusted > 0 ? `, target matrix moved by up to ${s.correlationAdjusted.toFixed(3)} to be achievable` : ''}`);
	for (const p of s.correlationProblems ?? []) out.push(`  correlation ignored: ${p}`);
	if (s.workers > 1) out.push(`  over ${s.workers} workers`);
	out.push(`  wall clock: ${((s.ms ?? 0) / 1000).toFixed(1)} s`);
	if (s.failed) {
		out.push(`  failed realisations: ${s.failed}`);
		for (const line of s.trouble ?? []) out.push(`    ${line}`);
	}
	if (prob.screen) {
		out.push(`  categories: ${prob.screen.counts.join(', ')} (last is Other); ${prob.screen.kept} of ${prob.iterations} shown`);
	}
	return out;
}

/** The whole log as one text. */
export function runLogText(parts) {
	return parts.filter((l) => l != null).join('\n');
}
