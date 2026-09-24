/**
 * What each simulation setting is, for the information panel (./infopanel.js).
 *
 * One topic per row of the Simulation section, written for somebody looking at
 * the row and wondering what to put in it: what the setting does, what an
 * empty box means and what number that comes to for the solver chosen, what
 * the choices are, and where the setting is kept in the model file. The panel
 * replaces the tooltips these rows had, so everything a tooltip said is here,
 * and the defaults it could not say.
 *
 * Every topic is worked out when the panel is drawn, from the model as it is
 * then (`ctx`), so the defaults are the chosen solver's and a choice says
 * which of its options is the one in force.
 */

import {
	SOLVER_INFO, SOLVER_IDS, SOLVER_OPTION_INFO, SOLVER_OPTIONS, solverDefault, solverOptions,
	solverIgnores, PORTED_IDS,
} from '../ode/solvers.js';
import {
	SPLIT_MODES, AUTO_STATES, AUTO_SOLVE_MS, AUTO_GAIN, AUTO_GAIN_UNTIMED,
} from '../sim/split.js';
import { DEFAULT_SIMULATION } from '../domain/project.js';

const KICKER = 'Simulation setting';

/** A number as a setting is written: `1e-6`, `250`, `100000`. */
export function fmtSetting(v) {
	if (typeof v !== 'number') return String(v);
	if (v === Infinity) return 'no limit';
	if (!Number.isFinite(v)) return String(v);
	if (v !== 0 && (Math.abs(v) >= 1e6 || Math.abs(v) < 1e-3)) {
		return v.toExponential().replace('e+', 'e').replace(/\.?0+e/, 'e');
	}
	return String(Number(v.toPrecision(6)));
}

/** A list in prose: `a, b and c`. */
const prose = (items) => (items.length > 1
	? `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}` : items[0] ?? '');

/** What the box holds now, as the panel's first fact. */
const now = (sim, key, unit = '') => {
	const v = sim?.[key];
	if (v == null || v === '') return 'empty';
	return `${typeof v === 'number' ? fmtSetting(v) : v}${unit ? ` ${unit}` : ''}`;
};

/**
 * The topic for one row.
 *
 * @param {string} key  the setting's key in `simulation`, or the name of a row
 *   that is not one (`scenario`, `run_together`, `advanced`, `dydp`, ...)
 * @param {object} ctx
 * @param {object} ctx.sim        the model's `simulation`, as it stands
 * @param {string} ctx.solver     the solver chosen
 * @param {(id: string) => string} ctx.solverLabel  a solver's name as the list shows it
 * @param {string[]} [ctx.scenarios]  the scenarios, when there are any
 * @param {string|null} [ctx.scenario]  the one selected
 * @returns {object|null} the topic, or null for a key with none
 */
export function simTopic(key, ctx) {
	const sim = ctx.sim ?? {};
	const unit = sim.time_unit ?? DEFAULT_SIMULATION.time_unit;
	const span = Number(sim.end_time ?? DEFAULT_SIMULATION.end_time) - Number(sim.start_time ?? DEFAULT_SIMULATION.start_time);
	const label = (id) => ctx.solverLabel?.(id) ?? SOLVER_INFO[id]?.label ?? id;
	if (SOLVER_OPTION_INFO[key]) return optionTopic(key, ctx, { unit, span, label });
	switch (key) {
		case 'scenario': return {
			kicker: KICKER,
			title: 'Scenario',
			lead: 'Which of the model’s alternative futures it is built at. Every block indexed by '
				+ 'the scenario list is read at the scenario chosen here, as if it were not indexed by '
				+ 'it at all, so an expression reading such a block needs no scenario dimension of its own.',
			facts: [
				['Now', ctx.scenario ?? '—'],
				['Scenarios', ctx.scenarios?.length ? prose(ctx.scenarios) : null],
				['In the model file', '`scenario`'],
				['Empty means', 'the first scenario'],
			],
			sections: [{
				text: [
					'A scenario list is an index list marked as the scenarios — **edit** beside the name '
					+ 'opens it. A parameter indexed by it holds one value per scenario and the run sees one '
					+ 'of them; switching the scenario here switches every one of them at once.',
					'The probabilistic run, the tornado and the sensitivities are always of this scenario. '
					+ 'To run others beside it, tick them under **Run**.',
				],
			}],
		};
		case 'run_together': return {
			kicker: KICKER,
			title: 'Run scenarios together',
			lead: 'Scenarios to run beside the selected one. Each runs as a run of its own — the '
				+ 'same model with that scenario selected — on a core of its own, so on a machine '
				+ 'with the cores they take about as long together as the slowest of them alone.',
			facts: [
				['Always run', ctx.scenario ?? '—'],
				['Kept in the model file', 'no — it changes no number of any scenario'],
			],
			sections: [{
				heading: 'What you get',
				list: [
					'The chart draws every selected output once per scenario, as `Soil · Drier`. An '
					+ 'output keeps its colour and each scenario wears a line pattern of its own; with one '
					+ 'output selected, each scenario takes a colour instead. The legend switches a '
					+ 'scenario’s lines off and on.',
					'The table has a column per output per scenario, and CSV and HDF5 exports write every '
					+ 'scenario.',
					'The status line says how many are in; the run log lists each with its steps and time.',
				],
			}, {
				heading: 'How they run',
				text: 'Ticking one while the results on screen are current runs just that one; unticking '
					+ 'one throws its run away. After an edit, Run runs them all. How many run at once '
					+ 'follows the Cores setting of the probabilistic dialog: the number chosen there, or '
					+ 'every core but one.',
			}],
		};
		case 'start_time': return {
			kicker: KICKER,
			title: 'Start',
			lead: 'When the run starts, in the model’s time unit. The initial amounts of the '
				+ 'compartments are the state at this time.',
			facts: [
				['Now', now(sim, 'start_time', unit)],
				['New model', `${DEFAULT_SIMULATION.start_time} ${unit}`],
				['In the model file', '`simulation.start_time`'],
			],
			sections: [{
				text: 'A logarithmic output grid cannot start at zero; it starts at the first time the '
					+ 'scale can hold, and nothing between the start and that time is saved — it is '
					+ 'still integrated.',
			}],
		};
		case 'end_time': return {
			kicker: KICKER,
			title: 'End',
			lead: 'When the run ends, in the model’s time unit.',
			facts: [
				['Now', now(sim, 'end_time', unit)],
				['New model', `${fmtSetting(DEFAULT_SIMULATION.end_time)} ${unit}`],
				['In the model file', '`simulation.end_time`'],
			],
			sections: [{
				text: 'The run’s length also sets two defaults: the output grid is spread over it, and '
					+ 'the longest step the solvers `ndf`, `ros23` and `dp45` take, unless told, is a tenth '
					+ `of it — ${fmtSetting(span / 10)} ${unit} now.`,
			}],
		};
		case 'output_points': return {
			kicker: KICKER,
			title: 'Output points',
			lead: 'How many times the results are reported at, spread over the run as the time '
				+ 'spacing says. More points make a finer chart and table.',
			facts: [
				['Now', now(sim, 'output_points')],
				['New model', String(DEFAULT_SIMULATION.output_points)],
				['In the model file', '`simulation.output_points`'],
			],
			sections: [{
				text: [
					'They do not change the solution: the solver takes whatever steps the tolerances need '
					+ 'and answers at these times from its own interpolant. They change what can be seen '
					+ 'of it — a peak between two points is drawn as the line between them.',
					'Not asked for with a list of series, which carries its own counts, or with the '
					+ 'solver’s own points, which are however many it takes.',
				],
			}],
		};
		case 'spacing': return {
			kicker: KICKER,
			title: 'Time spacing',
			lead: 'How the times the results are reported at are chosen.',
			facts: [
				['Now', now(sim, 'spacing')],
				['New model', DEFAULT_SIMULATION.spacing],
				['In the model file', '`simulation.spacing`'],
			],
			sections: [{
				choices: [
					['Logarithmic', 'Equal ratios, from the first point the scale can hold to the end. What '
						+ 'a result spanning decades is read in — and nothing between the start and that '
						+ 'first point is saved.', sim.spacing === 'log'],
					['Linear', 'Equal steps from start to end.', sim.spacing === 'linear'],
					['Several series…', 'A list of series combined into one set of times: a logarithmic '
						+ 'one for the run and an even one for its first year, say, plus any times written '
						+ 'out by hand. Ecolego’s own TimeSeriesList.', sim.spacing === 'series'],
					['The solver’s own points', 'No grid: the result is reported at every step the '
						+ 'solver takes, which are small where the answer moves and large where it does not. '
						+ 'Ecolego’s default, “Produce no additional output”.', sim.spacing === 'solver'],
					['Series and the solver’s points', 'Both, merged: the times asked for and every step '
						+ 'the solver took between them. Ecolego’s “Produce additional output”.',
					sim.spacing === 'both'],
				],
			}, {
				text: 'A model reported at the solver’s own points is never split into parts, since '
					+ 'every part would take different steps.',
			}],
		};
		case 'saved_times': return {
			kicker: KICKER,
			title: 'Saved times',
			lead: 'The series the output times are made of, combined into one set. Click the summary '
				+ 'to edit them.',
			facts: [['In the model file', '`simulation.output_times`']],
			sections: [{
				text: 'Each series is a start, an end, a count and a spacing, or a list of times written '
					+ 'out. A series entirely outside the run saves nothing, and is marked so.',
			}],
		};
		case 'time_unit': return {
			kicker: KICKER,
			title: 'Time unit',
			lead: 'The unit every time in the model is in: the span above, every rate per unit time, '
				+ 'every half-life’s decay constant.',
			facts: [
				['Now', now(sim, 'time_unit')],
				['New model', DEFAULT_SIMULATION.time_unit],
				['In the model file', '`simulation.time_unit`'],
			],
			sections: [{
				text: 'Changing it re-derives the unit of every flux in the model. It does not rescale '
					+ 'numbers: a rate of 0.1 per year becomes 0.1 per day.',
			}],
		};
		case 'solver': return solverTopic(ctx, label);
		case 'rtol': return {
			kicker: KICKER,
			title: 'Relative tolerance',
			lead: 'The error a step may make, as a fraction of each quantity’s own size. 1e-6 is '
				+ 'about six significant digits.',
			facts: [
				['Now', now(sim, 'rtol')],
				['New model', fmtSetting(DEFAULT_SIMULATION.rtol)],
				['In the model file', '`simulation.rtol`'],
			],
			sections: [{
				text: [
					'Tighter is slower and more accurate. It controls each step’s error, not the '
					+ 'error at the end, which can be several times larger after many steps.',
					'The way to know a result is resolved: run again with it ten times tighter. If what you '
					+ 'read off the chart does not move, it is.',
				],
			}],
		};
		case 'abstol': return {
			kicker: KICKER,
			title: 'Absolute tolerance',
			lead: 'The error allowed on a quantity near zero, in its own units. Below it a quantity is '
				+ 'not controlled, so set it below the smallest amount that matters.',
			facts: [
				['Now', now(sim, 'abstol')],
				['New model', fmtSetting(DEFAULT_SIMULATION.abstol)],
				['In the model file', '`simulation.abstol`'],
			],
			sections: [{
				text: [
					'A step is accepted when every quantity’s error is within rtol × its size + '
					+ 'abstol: the relative tolerance governs quantities well above abstol, this one those '
					+ 'near zero.',
					'A compartment can carry its own absolute tolerance, in its settings, for one whose '
					+ 'amounts are on another scale from the rest.',
				],
			}],
		};
		case 'non_negative': return {
			kicker: KICKER,
			title: 'Cannot go negative enabled',
			lead: 'The switch over every compartment’s own “cannot go negative”.',
			facts: [
				['Now', sim.non_negative === false ? 'off' : 'on'],
				['New model', 'on'],
				['In the model file', '`simulation.non_negative`'],
			],
			sections: [{
				list: [
					'**On**, each compartment decides for itself, which is the default and what every '
					+ 'compartment says unless it was changed.',
					'**Off**, nothing is held at zero anywhere in the model and the equations are '
					+ 'integrated as written — negative inventories and all. The per-compartment '
					+ 'settings are left untouched and simply not consulted, so turning it back on restores '
					+ 'exactly what the model said.',
				],
			}, {
				text: 'Ecolego calls it ‘Enable saturation’ and defaults it off; this tool defaults '
					+ 'it on, because the floor is the only part of saturation it carries. A compartment '
					+ 'held at zero is counted in the status line: it usually means a rate with the wrong '
					+ 'sign rather than a result.',
			}],
		};
		case 'mass_balance': return {
			kicker: KICKER,
			title: 'Mass balance',
			lead: 'Audit the bookkeeping of the run: whether the inventories account for everything '
				+ 'that came in, went out, decayed and grew in, at every output time.',
			facts: [
				['Now', sim.mass_balance === true ? 'on' : 'off'],
				['New model', 'off'],
				['In the model file', '`simulation.mass_balance`'],
			],
			sections: [{
				text: [
					'On, the run carries a budget per radionuclide — in from outside, out, lost to '
					+ 'decay, gained by ingrowth, moved by an explicit dy/dt term — and the status line '
					+ 'says whether the books close. They should, to within the solver’s tolerance; a '
					+ 'residual well above it is a compartment held at zero while its equations pushed it '
					+ 'below, or an amount the model moved that nothing accounts for.',
					'Off by default: it adds states to the vector and the run gives up the analytic '
					+ 'Jacobian, so it is a check to run, not a way to run.',
				],
			}],
		};
		case 'split': return splitTopic(sim);
		case 'advanced': return advancedTopic(ctx, { unit, span, label });
		case 'dydp': return {
			kicker: 'Analysis',
			title: 'Sensitivity (dy/dp)',
			lead: 'How much each block moves when one parameter moves, integrated alongside the model.',
			sections: [{
				text: 'Exact, and needs no distributions: it is the derivative at the values the model '
					+ 'holds, carried through the solve with it. Choose the parameters and the outputs in the '
					+ 'dialog; the answer is a curve per pair, absolute or relative.',
			}],
		};
		case 'calibration': return {
			kicker: 'Analysis',
			title: 'Optimise',
			lead: 'Solve for the parameter values that put chosen endpoints at chosen values, between '
				+ 'bounds you set.',
			sections: [{
				text: 'Nothing in the model is changed until you ask for it: the result can be previewed '
					+ 'on the chart first, and written into the model or left.',
			}],
		};
		case 'uncertainty': return {
			kicker: 'Analysis',
			title: 'Probabilistic',
			lead: 'Integrate the model once per realisation, drawing each distributed parameter from '
				+ 'its distribution, and draw the spread of the results.',
			sections: [{
				text: 'The dialog says what the run will cost before it starts, and shares the '
					+ 'realisations over the cores. Only shown for a model with a distribution: without one '
					+ 'every realisation would be the same.',
			}],
		};
		case 'analyse': return {
			kicker: 'Analysis',
			title: 'Analyse',
			lead: 'What a sample can be asked once it stands, and the runs that need no sample.',
			sections: [{
				list: [
					'**Distribution summary** — one output at one time as a distribution, with fits.',
					'**Categories** — classify the realisations and show only some.',
					'**Bands** — which percentiles the chart draws.',
					'**Tornado** — each input swung to two percentiles, one at a time.',
					'**Global sensitivity** — designed methods over the inputs’ distributions.',
					'**Replay a realisation** — one realisation of the sample, run again in full.',
				],
			}],
		};
		case 'what_drove': return {
			kicker: 'Analysis',
			title: 'What drove it',
			lead: 'Which sampled inputs the output on the chart depends on, from the realisations '
				+ 'already run.',
			sections: [{
				text: 'Correlations, regression coefficients and distribution-based measures, at a time '
					+ 'you choose or at each realisation’s peak. Nothing is run again.',
			}],
		};
		default:
			return null;
	}
}

/** The solvers, the chosen one marked. */
function solverTopic(ctx, label) {
	const current = ctx.solver;
	const choice = (id) => [label(id), SOLVER_INFO[id]?.blurb ?? '', id === current];
	const own = SOLVER_IDS.filter((id) => !PORTED_IDS.includes(id) && !SOLVER_INFO[id]?.remote);
	const remote = SOLVER_IDS.filter((id) => SOLVER_INFO[id]?.remote);
	return {
		kicker: KICKER,
		title: 'Solver',
		lead: 'Which integrator solves the model. The first is the default, and right for most '
			+ 'models here, which are stiff.',
		facts: [
			['Now', label(current)],
			['New model', label(DEFAULT_SIMULATION.solver)],
			['In the model file', `\`simulation.solver\` = \`${current}\``],
		],
		sections: [
			{ heading: 'This tool’s own', choices: own.map(choice) },
			{
				heading: 'Ported from DifferentialEquations.jl',
				text: 'Methods from SciML’s stiff suite, a second opinion that needs no download.',
				choices: PORTED_IDS.filter((id) => SOLVER_INFO[id]).map(choice),
			},
			...(remote.length ? [{
				heading: 'SciPy',
				text: 'Downloads a Python runtime, about 22 MB, the first time one is used, then keeps it '
					+ 'for the session. Needs a network connection; the others do not.',
				choices: remote.map(choice),
			}] : []),
			{
				text: 'Each reads its own settings beyond the tolerances, under **Advanced settings**.',
			},
		],
	};
}

/** Split into parts. */
function splitTopic(sim) {
	const mode = sim.split ?? 'auto';
	return {
		kicker: KICKER,
		title: 'Split into parts',
		lead: 'Solve a model that falls apart into independent parts — a decay chain each, on '
			+ 'most assessments — one part per core, each at its own steps. The run then takes as '
			+ 'long as its slowest part.',
		facts: [
			['Now', SPLIT_MODES.find(([k]) => k === mode)?.[1] ?? mode],
			['Empty means', 'auto'],
			['In the model file', '`simulation.split`'],
		],
		sections: [{
			choices: SPLIT_MODES.map(([k, name, what]) => [name, what, k === mode]),
		}, {
			heading: 'What auto decides',
			list: [
				`A model not yet timed is split from ${AUTO_STATES.toLocaleString('en')} states up, when its `
				+ `largest part is small enough to promise ${AUTO_GAIN_UNTIMED}× over the cores there are.`,
				`Once a whole solve has been timed, when it took over ${AUTO_SOLVE_MS / 1000} s and the parts `
				+ `are expected to be ${AUTO_GAIN}× faster.`,
				'Once the model has been split, what the split was measured to gain decides the next run.',
			],
		}, {
			heading: 'Worth knowing',
			text: [
				'The parts agree with a whole solve to within the tolerance, not to the last digit: each '
				+ 'takes the steps its own states need rather than the steps the stiffest state anywhere '
				+ 'needs, which is the point.',
				'A model is solved whole whatever this says when it carries a delay, a snapshot or a '
				+ 'discrete event; when it reports the solver’s own steps; with a SciPy solver; or when '
				+ 'it is one part. The status line says when a run was split, and the run log why or why not.',
			],
		}],
	};
}

/** Advanced settings, as a whole: what an empty box means, setting by setting. */
function advancedTopic(ctx, { unit, span, label }) {
	const id = ctx.solver;
	const keys = solverOptions(id);
	const dropped = solverIgnores(id);
	const sim = ctx.sim ?? {};
	return {
		kicker: KICKER,
		title: 'Advanced settings',
		lead: 'The settings the chosen solver reads beyond the tolerances. An empty box, or a choice '
			+ 'left on auto, is the solver’s own choice — which is what these numbers are, for this '
			+ 'solver and this run.',
		facts: [['Solver', label(id)], ...keys.map((k) => {
			const info = SOLVER_OPTION_INFO[k];
			const d = solverDefault(k, id, { span });
			const set = sim[k] != null && sim[k] !== '';
			const u = info.unit === true ? unit : (info.unit || '');
			const value = set
				? `${typeof sim[k] === 'boolean' ? (sim[k] ? 'on' : 'off') : fmtSetting(sim[k])}${u ? ` ${u}` : ''} — set`
				: `${defaultWords(d, u)}`;
			return [info.label, value];
		})],
		sections: [{
			text: [
				'Point at the (i) beside any of them for what it does. Leave them empty unless a run asks '
				+ 'for it — a solver that stalls, a model whose answer moves when the tolerances do.',
				dropped.length ? `This solver does not read ${prose(dropped)}, so they are not shown.` : '',
			].filter(Boolean),
		}],
	};
}

/** One solver setting. */
function optionTopic(key, ctx, { unit, span, label }) {
	const info = SOLVER_OPTION_INFO[key];
	const id = ctx.solver;
	const sim = ctx.sim ?? {};
	const d = solverDefault(key, id, { span });
	const u = info.unit === true ? unit : (info.unit || '');
	// By the ids the model file writes: the names carry commas of their own,
	// and a list of them in prose cannot be read.
	const readers = Object.keys(SOLVER_OPTIONS).filter((s) => SOLVER_OPTIONS[s].includes(key)).map((s) => `\`${s}\``);
	const set = sim[key] != null && sim[key] !== '';
	const shownNow = !set ? (info.kind === 'switch' ? 'off' : 'empty')
		: typeof sim[key] === 'boolean' ? (sim[key] ? 'on' : 'off') : `${fmtSetting(sim[key])}${u ? ` ${u}` : ''}`;
	const choices = info.kind === 'choice'
		? [['auto', `The solver’s own choice: ${d.text}.`, !set],
			...info.choices.map((c) => {
				const [value, name] = Array.isArray(c) ? c : [c, String(c)];
				return [String(name), '', set && String(sim[key]) === String(value)];
			})]
		: null;
	return {
		kicker: 'Advanced solver setting',
		title: info.label,
		lead: info.blurb,
		facts: [
			['Solver', label(id)],
			['Now', shownNow],
			[info.kind === 'switch' ? 'Off means' : 'Empty means', defaultWords(d, u, true)],
			['Unit', u || null],
			['In the model file', `\`simulation.${key}\``],
			['Read by', readers.join(', ')],
		],
		sections: choices ? [{ heading: 'Choices', choices }] : [],
	};
}

/** A default in words, with its number where it has one. */
function defaultWords(d, unit = '', long = false) {
	if (d.value == null || typeof d.value === 'boolean') return d.text;
	if (typeof d.value === 'string') return long ? d.text : d.value;
	if (d.value === Infinity) return 'no limit';
	const n = `${fmtSetting(d.value)}${unit ? ` ${unit}` : ''}`;
	return d.text === fmtSetting(d.value) || /^\d/.test(d.text) ? (long ? d.text : n)
		: `${n} — ${d.text}`;
}
