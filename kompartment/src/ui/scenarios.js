/**
 * Several scenarios at once.
 *
 * A scenario list is not an axis of the model but a set of alternative
 * futures, and this tool builds the model at one of them: every block indexed
 * by the list is read at the selected scenario (see *Scenarios* in GUIDE.md).
 * Ecolego runs one simulation per scenario. Here the selected one is the run
 * the page has always made, and the others chosen beside it run as runs of
 * their own -- the same model with another scenario selected -- each in a
 * worker of its own, so that on a machine with the cores they take no longer
 * together than the slowest of them alone. Nothing about a scenario's run
 * depends on another's, so they are exact: each is what running that scenario
 * on its own would give.
 *
 * The results stay where they were computed, as a run's always have (see
 * ../worker/sim-worker.js): the page holds each scenario's list of outputs and
 * asks its worker for the series a chart or a table is showing. The chart draws
 * every selected output once per scenario, and the table and the exports carry
 * a column per output per scenario.
 *
 * Only the rules are here -- which scenarios, what a line is called, how the
 * lines of several scenarios share a chart's colours -- so that they can be
 * tested without a page. Starting the workers and drawing is in ./app.js.
 */

import { scenarioNames, activeScenario, setScenario } from '../domain/edit.js';

/**
 * The scenarios a run covers, in the model's order: the selected one, which
 * always runs, and whichever others were chosen beside it. A chosen name the
 * model no longer has -- renamed, removed, switched off -- is dropped.
 *
 * @param {object} raw          the model
 * @param {Iterable<string>} chosen  the names ticked to run together
 * @returns {string[]}
 */
export function scenariosToRun(raw, chosen) {
	const names = scenarioNames(raw);
	const active = activeScenario(raw);
	const want = new Set(chosen ?? []);
	if (active) want.add(active);
	return names.filter((n) => want.has(n));
}

/** The scenarios that run beside the selected one: those, less it. */
export function otherScenarios(raw, chosen) {
	const active = activeScenario(raw);
	return scenariosToRun(raw, chosen).filter((n) => n !== active);
}

/**
 * The model as it runs in scenario `name`: a copy with that one selected,
 * which is all a scenario is to the builder.
 */
export function scenarioModel(raw, name) {
	const copy = structuredClone(raw);
	setScenario(copy, name);
	return copy;
}

/** What a line is called on a chart that holds more than one scenario. */
export const scenarioLabel = (label, name) => `${label} · ${name}`;

/**
 * How many runs to have going at once: the reader's number of cores where
 * they chose one, otherwise every core the machine reports but one, which is
 * what a sampled run leaves the page as well. Never fewer than one.
 *
 * @param {number|null} chosen  from ./cores.js `chosenCores()`
 * @param {number|null} machine from `machineCores()`
 */
export function runsAtOnce(chosen, machine) {
	if (Number.isInteger(chosen) && chosen >= 1) return chosen;
	const m = Number.isInteger(machine) && machine >= 1 ? machine : 4;
	return Math.max(1, m - 1);
}

/**
 * The lines of a chart over several scenarios.
 *
 * `primary` is what the chart would draw for the selected scenario alone --
 * one line per selected output, or several where a sample puts a median and a
 * mean through it. `others` are the scenarios beside it, each with its lines
 * for the same outputs in the same order (`pos` is the output's place in the
 * selection).
 *
 * The house rule for two lines of one thing is that the colour says which
 * output it is and the pattern says which line of it (see `styleOf` in
 * ./chart.js), and scenarios follow it: an output keeps its colour in every
 * scenario and each scenario wears a pattern of its own. Except for a chart of
 * one output, where the patterns would be the only difference between lines
 * that have nothing else to tell apart: there each scenario takes a colour.
 *
 * A scenario keeps its colour or its pattern when another is hidden: `at` is
 * its place among all the scenarios run, the selected one being 0, and the
 * style follows that rather than its place among those drawn.
 *
 * A chart holds at most `max` lines; what does not fit is counted, not drawn.
 *
 * @param {Array<object>} primary   the selected scenario's series, empty when
 *   it is hidden
 * @param {{active: string, others: Array<{name: string, at: number, lines:
 *   Array<{pos: number, label: string, values: ArrayLike<number>, unit?: string}>}>,
 *   outputs: number, perOutput?: number, max: number}} opts  `outputs` is how
 *   many outputs are selected and `perOutput` how many lines the selected
 *   scenario draws for each -- two for a sample's median and mean
 * @returns {{series: Array<object>, dropped: number}}
 */
export function withScenarios(primary, { active, others, outputs, perOutput = 1, max }) {
	if (!others.length) return { series: primary, dropped: 0 };
	// One output with one line of it: the scenarios are the only thing to tell
	// apart, so each gets a colour. A sample's median and mean are already
	// told apart by their patterns, and keep them.
	const byScenario = outputs === 1 && perOutput === 1;
	const series = primary.map((s) => ({
		...s,
		label: scenarioLabel(s.label, active),
		...(byScenario ? { slot: 0, set: undefined } : {}),
	}));
	// The patterns the selected scenario's own lines use, so that a scenario
	// beside it does not repeat one of them.
	const used = Math.max(1, perOutput);
	let dropped = 0;
	for (const o of others) {
		for (const line of o.lines) {
			if (series.length >= max) { dropped++; continue; }
			series.push({
				label: scenarioLabel(line.label, o.name),
				values: line.values,
				unit: line.unit,
				...(byScenario ? { slot: o.at } : { slot: line.pos, set: used + o.at - 1 }),
			});
		}
	}
	return { series, dropped };
}
