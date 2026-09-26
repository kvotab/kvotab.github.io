/**
 * Application shell.
 *
 * Six views over one model:
 *
 *   Build     graphical editor -- drag compartments, draw transfers
 *   Matrix    the from/to transfer grid
 *   Chart     results over time
 *   Table     the same numbers, for reading and copying
 *   JSON      the project file itself
 *   Code      the derivative function generated from the equations
 *
 * The graph, the matrix, the inspector and the JSON tab all edit the same plain
 * object; `state.raw` is the single source of truth and every view re-reads it.
 * Simulations run in a Worker so editing stays responsive.
 */

import { Project, DEFAULT_SIMULATION } from '../domain/project.js';
import * as ed from '../domain/edit.js';
import {
	TimeChart,
	MAX_SERIES,
	DEFAULT_SERIES,
	fmtValue,
	filterOutputs,
	filterGroups,
	seriesStyle,
	styleOf,
} from './chart.js';
import { PICTURE_KINDS } from './picture.js';
// The one rule CSV has, from the module both writers share. Statically, and
// four lines: the runner it used to live in is loaded on demand -- only the
// SciPy solvers need it here -- so reaching for it at export time found
// nothing, and every CSV export threw at the header line.
import { csvCell } from '../io/csv.js';
import { GraphEditor } from './graph.js';
import {
	renderInspector,
} from './inspector.js';
import { section as part, el } from './parts.js';
import { blockIcon, sampleMark, popIcon } from './icons.js';
import { openMenu } from './menu.js';
import { openModal, refreshModal, closeAllModals } from './modal.js';
import { openProbabilisticDialog, openReplayDialog, openBandsDialog, bandPairs } from './probdialog.js';
import { openSensitivityDialog } from './sensdialog.js';
import { openDistributionDialog } from './distdialog.js';
import { openCategoriesDialog } from './catdialog.js';
import { openTornadoSetup, openTornadoResult } from './tornadodialog.js';
import { openGsaSetup, openGsaResult } from './gsadialog.js';
import { categoriesOf } from '../domain/categories.js';
import { implicitInputs } from '../domain/uncertainty.js';
import { runLogLines, probabilisticLogLines, runLogText, scenarioLogLines } from '../domain/runlog.js';
import { compareModels, reportLines, summary as versionSummary } from '../domain/versions.js';
import { describeAudit } from '../domain/massbalance.js';
import { openLocalSensitivityPicker, openLocalSensitivityResult } from './localsensdialog.js';
import { openShapeSettings } from './shapedialog.js';
import { renderJacobianView } from './jacobianview.js';
import { openHandoff, handoffName } from './handoff.js';
import * as autosave from './autosave.js';
import * as shared from './clipboard.js';
import { workersFor } from '../worker/prob-pool.js';
import { SPLIT_MODES } from '../sim/split.js';
import { chosenCores, chooseCores, poolNote, machineCores } from './cores.js';
import {
	scenariosToRun, otherScenarios, scenarioModel, scenarioLabel, runsAtOnce, withScenarios,
} from './scenarios.js';
import { openQueryDialog } from './querydialog.js';
import * as dt from '../domain/datatable.js';
import { openDataImport } from './dataimport.js';
import { openSaveDialog } from './savedialog.js';
import { exportReportNodes } from './ecoreport.js';
import { openImportChooser } from './importchooser.js';
import { openOptimiseDialog } from './optdialog.js';
import { findBlock } from '../domain/blocks.js';
import { describeDataset } from '../io/dataset.js';
import { blocksOf, indicesFor } from './endpoints.js';
import {
	writeDataWorkbook, readDataWorkbook, writeDataHDF5, readDataHDF5,
} from '../io/datafile.js';
// What a histogram may be asked for, so the box that asks and the function
// that answers cannot disagree about it.
import { HIST_BINS } from '../domain/distribution.js';
import * as qa from '../domain/qa.js';
import * as Q from '../domain/queries.js';
import { availabilityProblems } from '../domain/availability.js';
import { parameterSlots, slotLabel } from '../sim/localsens.js';
import { buildSystem } from '../sim/builder.js';
// What a run *would* report, from the layout alone -- so the endpoint picker
// can offer its list before the model has been run.
import { outputsOf } from '../sim/runner.js';
import { samplingPlan, slotName, groupOf } from '../sim/probabilistic.js';
import { renderMatrix, markSelection } from './matrix.js';
import { UndoStack } from './undo.js';
import { renderBlockTree, treeTools } from './tree.js';
import { infoButton, refreshInfo, setInfoLinks } from './infopanel.js';
import { simTopic, fmtSetting } from './siminfo.js';
import { panelTopic } from './panelinfo.js';
import { wireJsonEditor } from './jsoneditor.js';
import { blockTopic } from './blockinfo.js';
import { slug as headingId } from './markdown.js';
import { renderInfo } from './info.js';
import { renderHelp, goToHelp, setBuildStamp } from './help.js';
import { renderHistograms, MOST_PANELS } from './histview.js';
import { renderScatter } from './scatterview.js';
// A block's title carries its symbol, which is elements rather than text.
import { symbolNodes } from './symbol.js';
import { attachCompletion, searchLook, completionIsOpen } from './complete.js';
import { renderIndexLists, selectIndexList } from './indexlists.js';
import { fmtTime } from './summary.js';
import { fillStartValues } from './startvalue.js';
import { baseName, parentOf, isWithin } from '../domain/systems.js';
import {
	SOLVER_IDS,
	DEFAULT_SOLVER,
	solverLabel,
	SOLVER_OPTION_INFO,
	solverOptions,
	solverIgnores,
	solverIsRemote,
	solverDefault,
} from '../ode/solvers.js';
import { dialogInfo } from './dialoginfo.js';

/**
 * Bumped whenever the app changes. Shown at the foot of the Help tab so that a
 * stale cached copy can be spotted -- browsers hold on to JavaScript modules,
 * and a Worker keeps its own module cache on top of the page's, which has
 * caused more than one "the code says otherwise" puzzle. Serve with serve.py,
 * which disables caching.
 */
const BUILD = '2026-09-26';

const EXAMPLES = [
	{ file: 'four-compartment.json', title: 'Four-compartment test model' },
	{ file: 'decay-chain.json', title: 'Neptunium series ingrowth' },
	{ file: 'biosphere.json', title: 'Repository to well' },
	{ file: 'landscape.json', title: 'Landscape objects (2-D)' },
	{ file: 'lookup-driver.json', title: 'A time-dependent driver' },
	{ file: 'post-processing.json', title: 'Dose from a released inventory' },
	{ file: 'recorders.json', title: 'Peak dose and when it happened' },
	{ file: 'scenarios.json', title: 'Three climate scenarios' },
	{ file: 'farfield.json', title: 'Fractured rock: a far-field path' },
	{ file: 'waste-packages.json', title: 'Canisters failing: a source term with barriers' },
];

/**
 * What **New** starts from: the simulation settings and nothing else.
 *
 * Empty rather than a worked example. It used to open on two compartments, a
 * transfer and a rate, which is a model somebody else wrote: whatever you meant
 * to build, the first thing to do with it was delete it, and renaming `A` and
 * `B` into what you actually wanted is slower than adding two boxes. The
 * examples in the picker beside the button are where a worked model belongs,
 * and there are nine of them.
 *
 * The settings stay, because they are not a model -- a run has to start
 * somewhere and end somewhere, and 0 to 1000 years on a log grid is the shape
 * of nearly every assessment this tool is for. Everything else is a canvas.
 */
const BLANK = {
	name: 'New model',
	description: '',
	// The model defaults, with the one thing a blank model wants different:
	// a thousand years rather than a hundred thousand. The tolerances, the
	// solver and the grid are not repeated here -- they were, and changing
	// them in `DEFAULT_SIMULATION` then changed them for every model *except*
	// a new one, which is the one place somebody would look.
	simulation: { ...DEFAULT_SIMULATION, end_time: 1000 },
	parameters: [],
	compartments: [],
	transfers: [],
	expressions: [],
	inflows: [],
};

/** A new model, dated now: the one time its making is known for certain. */
function blankModel() {
	return ed.stampCreated(structuredClone(BLANK));
}

/**
 * The two side panels: the left one that edits values, and the right-hand
 * rail. Each has a width, a floor, and a chevron that folds it away.
 *
 * `def` is what it opens at and what double-clicking the grip restores --
 * which is the width each panel had when it was fixed. `fold` and `unfold` are
 * the two directions the chevron points: towards the wall it folds against,
 * and back towards the middle it comes out into.
 */
const PANES = {
	// One, now. The right panel held the tree of the model and the reading
	// view of what was selected; both are in this one, below the simulation
	// settings, so a model's blocks are in one place rather than two. Wider by
	// default than it was, because it now carries what that panel carried.
	left: {
		panel: '#sidebar', width: '--left-w', name: 'left panel',
		def: 330, min: 220, fold: '\u2039', unfold: '\u203a',
	},
};

/**
 * What each simulation setting is called.
 *
 * One place, because two things name them: the field's own label, and the
 * problems strip when one of them is wrong. The strip used to print the key --
 * `output_points` beside a sentence of prose -- which is the model's spelling
 * rather than the reader's.
 */
const SIM_LABELS = {
	scenario: 'Scenario',
	// `Start` and `End` rather than `Start time`: the unit sits beside them as
	// a suffix, and in a 90px column the word `time` twice is the section's
	// own title repeated.
	start_time: 'Start',
	end_time: 'End',
	output_points: 'Output points',
	spacing: 'Time spacing',
	time_unit: 'Time unit',
	solver: 'Solver',
	rtol: 'Rel. tolerance',
	abstol: 'Abs. tolerance',
	// `... enabled`, where a compartment's own switch is just `cannot go
	// negative`: this is the one above them, and the row is a wide one with
	// the space to say which it is.
	non_negative: 'Cannot go negative enabled',
	mass_balance: 'Mass balance',
	split: 'Split into parts',
};

// ...and the solver's own settings, from the one table that says what they
// are. Written in here rather than repeated: `numField` and its two siblings
// look a label up by key, and a second copy of these would be a second place
// for them to go stale. See SOLVER_OPTION_INFO in ../ode/solvers.js.
for (const [key, info] of Object.entries(SOLVER_OPTION_INFO)) SIM_LABELS[key] = info.short ?? info.label;

/**
 * The settings that change how the model is *solved* and nothing about it.
 *
 * An edit to one of these cannot move a block, a name, a value, a unit or a
 * dimension, so the diagram, the matrix and the tree of every block in the
 * model are already showing the right thing and do not need building again.
 * On a model of 1,350 blocks that is most of what such an edit cost.
 *
 * Deliberately short. `time_unit` is a simulation setting that re-derives
 * every flux unit in the model; `scenario` changes which value each indexed
 * block reads; the span moves the saved-times warnings. Those are edits to
 * what is shown, whatever panel they are typed into, and they take the full
 * path like any other.
 */
const SOLVE_ONLY_SETTINGS = new Set(['solver', 'rtol', 'abstol', 'non_negative', 'split']);

/**
 * Where a problem that is not about a block sends you.
 *
 * A block's name is its own way in: click it and the diagram selects it. The
 * model has settings that are not blocks and can still be wrong -- the output
 * grid is the one that has warnings today -- and a row about one of those has
 * an editor to open rather than a name to select. `modelWarnings` names the
 * key; this says what it opens.
 */
const GOTO = {
	'saved-times': () => openSavedTimes(),
};

/**
 * What the middle keeps, whatever the panels are doing.
 *
 * Both panels can be dragged and both can be folded away, so between them they
 * could otherwise squeeze the diagram to nothing -- and a panel is dragged by
 * a grip that would then be sitting on top of the other one.
 */
const MIDDLE_MIN = 360;

const state = {
	raw: null,
	project: null,
	results: null,
	selection: null,
	// Everything selected on the diagram. `selection` is the one of them the
	// inspector shows; several can be moved or deleted together.
	picked: [],
	selected: [],
	xLog: true,
	yLog: true,
	running: false,
	runId: 0,
	// The selected scenario's own run is in flight. `running` covers the
	// whole of what Run started, which with scenarios beside it lasts until
	// the slowest of them is in; this is the one part of it the worker in
	// `ensureWorker` is doing.
	primaryBusy: false,
	// The scenarios chosen to run beside the selected one, by name, and their
	// runs -- name -> entry, see `startScenario`. Page state rather than the
	// model's: which futures are compared changes no number of any of them,
	// so it is not written into the file. `hiddenScenarios` are the ones whose
	// lines the chart's legend has switched off.
	scenarioChoice: [],
	scenarioRuns: new Map(),
	hiddenScenarios: new Set(),
	// How far the selected scenario's run has got, and its clock, as
	// `setProgress` last read them; `paintProgress` combines it with the
	// scenarios beside it.
	primaryFraction: 0,
	primaryAt: null,
	// How many cores the sampled run going now is on, from the worker's
	// `pool` message: `{workers, asked, why}`, or null. See ./cores.js.
	pool: null,
	dirty: false,
	// Off until it is asked for. It is the switch that makes a keystroke start
	// a solve, and on an imported assessment of fifty thousand states that is
	// a page that goes away for half a minute every time a digit is typed --
	// paid by everyone who opens one, to save a click for the people editing a
	// small model. The checkbox is beside Run and says what it does; the
	// chart, with no results, says the switch is off and offers the button.
	// `index.html` must agree: the state and the box are read independently.
	autoRun: false,
	// The last tornado, under its own run id like the probabilistic result.
	tornado: null,
	tornadoRunning: false,
	tornadoRev: null,
	// And the last global sensitivity design, the same way.
	gsa: null,
	gsaRunning: false,
	gsaRev: null,
	distFor: null,
	// The output times of the run in progress, and how many of them it has
	// reached: what the progress bar counts. See `setProgress`.
	grid: null,
	gridAt: 0,
	// The model's warnings, worked out once per scan and read twice -- by the
	// marks and by the strip. `modelWarnings` walks every equation in the
	// model and checks its units, which on a landscape model is most of a
	// second, and it was being done twice on every keystroke.
	warnings: [],
	// Whether the strip is showing everything it has rather than the first
	// few. Session state, not the model's: it is about what is being read
	// right now, and a model saved mid-read should not carry it.
	problemsExpanded: false,
	// How long the last solve took, and which solver took that long. The
	// timing decides whether re-running on every edit would get in the way,
	// and it is a fact about one solver on one model: SciPy's are two to
	// twenty times slower than the ones here, so a measurement taken under
	// one of them says nothing about dp45 and must not be inherited by it.
	lastSolveMs: 0,
	lastSolveSolver: null,
	tab: 'build',
	// Which left-panel sections are open. Defaults in SECTION_OPEN.
	sbSections: {},
	// The block-list filter. Not part of the project: it is a way of looking
	// at a model, not a fact about it, and it should not turn up in a diff.
	//
	// `only` is the answer to a structured question -- what reads this, what
	// nothing reads -- pinned over the list. It narrows rather than replaces,
	// so the name box and the kind chips still work on top of it. `onlyLabel`
	// is what to call it on screen, since a set of names is not self-describing.
	// `sample` is the Probabilistic chip: only what the sample on screen holds,
	// on top of the rest, and nothing at all while there is no sample.
	search: { query: '', kinds: new Set(), only: null, onlyLabel: '', sample: false },
	// Where the Information view has been, so following a reference can be
	// undone. Every selection is recorded, wherever it came from, which is
	// what a navigation history does.
	trail: { seen: [], at: -1, moving: false },
	// The block whose full settings dialog is open, if any. Tracked because
	// renaming a block inside the dialog changes the name the dialog is about.
	settingsFor: null,
	// The block tree: which sub-systems are open, and whether the blocks of
	// each are filed under a heading per kind. The top level starts open, so
	// a model that has just been opened shows its sub-systems and not a wall
	// of blocks.
	tree: { open: new Set(['']), group: false },
	// Which sub-systems are unfolded on the transfer grid. Closed by default:
	// the point of folding one is the overview, and a model with two hundred
	// sub-systems opened flat is the thing this replaces. The view's, never
	// the model's, so it is not saved and changing it marks nothing stale.
	matrixOpen: new Set(),
	// The same idea for the chart's series picker: a name pattern, the kinds
	// of output, one set of allowed indices per index list, and the same
	// Probabilistic chip the tree has.
	pick: { query: '', kinds: new Set(), indices: new Map(), sample: false },
	// The file this model was last written to, and the revision it was written
	// at. Together they are what makes Save mean *save* rather than *save a
	// copy somewhere*: with a file in hand the button writes to it and says
	// nothing, and the reader can see whether there is anything to write.
	//
	// Not kept across a reload. A handle can be stored in IndexedDB and asked
	// to prove its permission again on the way back, and a Save that silently
	// overwrote a file chosen in a previous session -- possibly in a previous
	// week -- is not what anybody means by pressing a button once.
	fileHandle: null,
	savedRev: null,
	// Which probabilistic run the picture below was chosen for, so it is chosen
	// once per run and not on every redraw.
	probModeFor: null,
	// Whether the Table lists a run over time or the realisations at one
	// instant, and which instant. The chart's own time is reused where the
	// reader has set one: asking the same question twice in two tabs is a way
	// of getting two answers.
	tableMode: 'time',
	// Which run the Table's rows are, over time, once there is a sample. A
	// column of numbers cannot say what it is by looking, and after a thousand
	// realisations there are several honest answers: the middle of them, their
	// average, one of them, the model at its own values, or all of them at
	// once. `raw` is the whole matrix -- time down, realisation across -- and
	// is offered for one series at a time, since a second would need a second
	// table beside it.
	tableSeries: 'median',
	// Which realisation, zero-based, when that is what is being shown.
	tableReal: 0,
	// What has been read back out of the sample for the Table: one realisation
	// of each selected series (`tableCols`), or the whole matrix of one series
	// (`tableRaw`). The page holds bands; the realisations are in the worker,
	// so both are fetched and both are keyed on what they are an answer to.
	tableCols: null,
	tableRaw: null,
	// How many realisations of the matrix are on screen. Null is the first
	// page of them; the button below it asks for more.
	tableRawCols: null,
	// What the line through a probabilistic band is, and what is drawn behind
	// it. The median with its percentile bands is the assessment's own picture
	// and the default; the mean answers a different question and the two are
	// far apart for a skewed output, which is why both are offered rather than
	// one being chosen for the reader.
	//
	// `single` is the model at its own values -- the deterministic run, drawn
	// as a line with no spread, which is what somebody who has just pressed
	// Run once is looking for.
	//
	// Any combination of the three, because comparing them is the point: how
	// far a skewed output's mean sits above its median, and where the one run
	// the model's own values give falls among the thousand, are questions
	// about two pictures at once. `chartLines` is never empty -- the last one
	// on cannot be turned off, since a chart with no line is not a picture of
	// anything.
	chartLines: { median: true, mean: false, single: false },
	// `bands` the percentile pairs, `sem` how well the line itself is known,
	// `sd` where the realisations are, `none` a bare line. The last two are
	// about whichever lines are up: ± 1.96 standard errors and ± one
	// standard deviation of the mean, and for the median the two intervals
	// read off the sorted realisations instead.
	chartSpread: 'bands',
	// The values a preview run was made at, or null for an ordinary run. The
	// model is not edited for one, so this is the only thing that knows the
	// numbers on screen are not the numbers in the file.
	preview: null,
	// How the last optimisation was set up. Kept on the page rather than in
	// the model: it is a question somebody is asking *of* the model, and a
	// half-written question is not a change to the file.
	optSetup: null,
	// The dialog while it is open, so the worker's progress can reach it.
	optOpen: null,
	optId: 0,
	// What the Save dialog was last set to, so a reader saving the same thing
	// twice does not have to say it twice. Not kept across a reload: a choice
	// made last week is not one anybody remembers making.
	saveChoice: { kind: 'model', format: 'json' },
	// How a distribution is binned. `null` bins is the rule -- Sturges' for a
	// single panel, a finer fixed count for the shared axis -- and a number is
	// the reader's own; `histScale` is what the bin *edges* are spaced by,
	// which decides what shape a sample appears to have and is a different
	// question from how the counts are drawn. `auto` puts a sample that spans
	// decades on a logarithmic spacing and everything else on an even one.
	histBins: null,
	histScale: 'auto',
	// Which series a scatter puts across the bottom, by label so it survives a
	// re-run that renumbers the outputs. Null is "the first one selected", so
	// a scatter draws something the moment it is asked for.
	scatterX: null,
	// Whether a scatter carries its least-squares line.
	scatterFit: true,
	// The answer, with what it was an answer to. See `askPoints`.
	points: null,
	// How the distributions are laid out: every one over a single axis, or a
	// panel each. All in one by default -- the series a reader ticks together
	// are usually the same quantity, and comparing them is the reason they
	// were ticked together. See ./histview.js.
	histArrange: 'one',
	// Which of the Chart tab's two pictures is up: the series over time, or
	// their distribution at one instant. `dist` needs realisations to take a
	// distribution *of*, so it is only reachable once a probabilistic run
	// stands -- and is chosen automatically when everything selected is a
	// quantity that does not vary over time, where a band is a flat line and
	// the shape is the whole of what there is to see.
	chartMode: 'time',
	// Which time the distribution is of. Null is the last, which is where a
	// band ends and the number an assessment usually quotes.
	chartAt: null,
	// The answer, with what it was an answer to. See `askHistograms`.
	hist: null,
	// What Copy took, waiting for a Paste. Not cleared by loading a model:
	// carrying a block from one model to another is the one thing this makes
	// possible that nothing else does.
	clipboard: null,
	// A block's look, for Paste format: see `copyFormat`.
	formatClip: null,
	// When it was taken. Compared against the copy another tab shared, so the
	// last thing copied *anywhere* is the thing that pastes -- see
	// ./clipboard.js and `clipboardNow` below.
	clipboardAt: 0,
	// What a Cut has marked to be moved: the names, and the sub-system they
	// were in. Nothing has happened to them; a Paste moves them, and any edit
	// takes the mark off. See `cutSelection`.
	pendingCut: null,
	// How the rail divides between the tree and Information, as the tree's
	// share of the two. A fraction rather than a height, so the division
	// survives the window being resized -- which is what someone who set it
	// meant by it.
	split: 0.56,
	// The two side panels: how wide each is, and whether it is showing.
	// Pixels rather than a fraction, unlike the rail's own divider: a panel
	// sized to fit the names in it should stay that wide when the window
	// changes and let the middle take the difference, which is what every
	// editor with side panels does. Built from PANES so the defaults are
	// written down once.
	panes: Object.fromEntries(Object.entries(PANES)
		.map(([side, spec]) => [side, { width: spec.def, shown: true }])),
	// Which version of the model the results on screen belong to. Bumped by
	// every edit that could change a number, and stamped onto the results when
	// a run starts -- so "are these results this model's?" is one comparison
	// rather than a guess. Results that are not the model's own are not shown
	// at all; see `resultsAreStale`.
	rev: 0,
	// What is wrong with the model, as a list, for as long as it is wrong.
	// Equation problems are re-scanned on every edit; a failed run's error
	// stays until the next run is attempted.
	problems: [],
	// The unit mismatches, from the same scan. Kept because two things read
	// them -- the warnings and the rail's information card -- and walking
	// every equation in the model twice for one answer was most of an edit.
	unitProblems: [],
	// What is wrong and where, as the diagram, the tree and the Information
	// view mark it: by block name and by every sub-system above one.
	marks: new Map(),
	runProblem: null,
	// What the last run warned about, block by block: a far-field path worked
	// out semi-analytically whose unit response missed its mass balance (the
	// run's `stats.farfield`). Warnings, not faults -- the run went on -- and
	// replaced by the next run's.
	runWarnings: [],
	// What the build behind the values at the start found, when it would not
	// build: the same fault a run would stop on, found without one. See
	// `noteBuildProblem`.
	buildProblem: null,

	/**
	 * A copy of every locked block, as it stood when the lock was last honoured.
	 *
	 * A lock has to bite on *editing*, and editing happens in about fifty
	 * functions. Guarding each of them is a lock that one unusual path walks
	 * round, which is no lock at all — so it is enforced at `modelChanged`
	 * instead, which every edit goes through without exception, by comparing
	 * what the blocks are against what they were and putting back anything a
	 * lock was holding.
	 *
	 * Only the locked ones, so this is a handful of blocks rather than a second
	 * copy of the model: the undo stack goes to some trouble to avoid holding
	 * one of those and this should not undo that.
	 */
	locked: new Map(),

	// --- the run, and what it produced -------------------------------------
	// Everything below used to be created by assignment where it was first
	// needed, which is how `prob` came to outlive the model it was of: the
	// list `setModel` resets was written against this literal, and a field
	// that was not in it was never in that list either. Declared here, so
	// that what the views read is one list that can be read through.

	/**
	 * The last probabilistic run: its bands, its outputs, the id the worker
	 * still holds its matrix under, and **the revision of the model it was a
	 * run of**.
	 *
	 * The revision is what makes it droppable. A band is a statement about
	 * one model; drawn under a line from a different one -- an edit later, or
	 * a different file altogether -- it is a picture of two models at once,
	 * and nothing about it looks wrong. Read through `currentProb()`, never
	 * directly, so there is one place that decides whether it still applies.
	 */
	prob: null,
	// The model as it was opened -- `{text, label}` -- for the version report.
	opened: null,
	probRunning: false,
	// The revision the probabilistic run was launched from, stamped onto
	// `prob` when it lands -- the same trick `runRev` plays for `results`.
	probRev: 0,
	// Which output *What drove it* was asked about, for naming the answer.
	sensFor: null,

	// The fingerprint of the model the results on screen were solved from,
	// and the one the run in flight was launched with. See
	// `integrationKeyNow` and `ed.integrationFingerprint`.
	integrationKey: null,
	runKey: null,
	// The revision and the solver a run was launched with, stamped onto the
	// results when they arrive rather than read at that point: an edit made
	// while the solver worked must not pass itself off as included.
	runRev: 0,
	runSolver: null,
	// Whether the run in flight asked the worker to re-evaluate rather than
	// solve. Only for what the footer says about it.
	reusing: false,
	// The labels the last run produced, so a selection can be carried across
	// a re-run by name rather than by position.
	prevLabels: null,

	// The chart's series picker: which chip's index menu is open, and how
	// many chips are drawn. Set by `setModel` from MAX_PICK_CHIPS, which is
	// declared beside the code that reads it.
	pickOpen: null,
	// What has been typed into that open chip's own filter.
	pickPopQuery: '',
	pickChips: 0,
	// How many rows the table draws, from TABLE_ROWS, likewise.
	tableRows: 0,
};

/** What either pane of the rail may be squeezed to, in pixels. */
const RAIL_MIN = { tree: 118, info: 96 };

let worker = null;
let chart = null;
let graph = null;
let autoRunTimer = null;
/**
 * Every state the model has been in since it was opened.
 *
 * Outside `state` on purpose: `state` is what the views read, and this is
 * where the views have been. Loading a model starts it over -- undo does not
 * reach back across a file, because the thing it would put back is not on
 * screen any more and could not be looked at before accepting it.
 */
const undoStack = new UndoStack();
/**
 * The draft this tab keeps, so a refresh is not the end of an hour's work.
 *
 * Written after the typing stops rather than on every edit, and only when the
 * model fits in what a browser will hold -- see ./autosave.js, which has the
 * reasoning and the ceiling. Everything it can fail at, it fails at quietly
 * except one: a model too large to keep is said once, because a draft nobody
 * knows is not being written is worse than no draft.
 */
const draftKeeper = autosave.autosaver({
	onRefused: (r) => flash(
		`This model is not being kept for next time: ${r.why}`
		+ (r.bytes ? ` (${Math.round(r.bytes / 1048576)} MB).` : '.')
		+ ' Save it to a file to be sure of it.', 'warn'),
});

/** What the draft is filed under, so the offer can name it. */
function draftMeta() {
	return { label: modelSource?.label ?? state.raw?.name ?? UNTITLED, name: state.raw?.name ?? '' };
}
/**
 * A run that was wanted while one was already going.
 *
 * With auto-run on, the chart follows the model; a run refused because one is
 * in flight has to happen when that one lands, or the edit that asked for it
 * is silently dropped. The first SciPy run is where this bit: it spends
 * seconds downloading a Python runtime, and anything edited in that window --
 * including changing the solver again -- left the model dirty with nothing
 * coming, and only the Run button to get out of it.
 */
let runWanted = false;
// ... and whether that remembered run was asked for by hand (Run, Cmd-Enter),
// which is honoured when it comes round even with auto-run switched off.
let runWantedManual = false;
/** Set during boot; reflects the project's view flags onto the checkboxes. */

const $ = (sel) => document.querySelector(sel);

const put = (node, ...kids) => {
	for (const k of kids.flat()) {
		if (k == null || k === false) continue;
		node.append(k.nodeType ? k : document.createTextNode(String(k)));
	}
	return node;
};

// `el` comes from ./parts.js, which is where the one copy lives: this file
// had a second, and the two drifted the moment one of them learned that a
// hyphenated property is an attribute. Every `aria-label` in the left panel
// was a plain field on the element, which no screen reader ever sees.

// --- running --------------------------------------------------------------

function workerAvailable() {
	if (new URLSearchParams(location.search).has('mainthread')) return false;
	if (typeof Worker === 'undefined') return false;
	if (location.protocol === 'file:') return false;
	return true;
}

/**
 * Whether a message from the worker is still wanted.
 *
 * Everything a run reports -- its progress, its results, its error -- belongs
 * to the run in flight, and a reply from one that has been abandoned is noise.
 *
 * A `columns` reply is the exception, and the reason this is a function rather
 * than one comparison. Those columns belong to the *results on screen*, and
 * are asked for under the id of the run that produced them -- which stops
 * being the current id the moment a probabilistic or a sensitivity run takes
 * the next one. Matched against the current id instead, the reply was thrown
 * away on arrival; the indices stayed marked as asked, so nothing ever asked
 * again; and an export sat waiting for columns the page had already been
 * handed. It printed "Working out 59 series..." and never printed anything
 * else. `acceptColumns` does the matching that is actually right, against the
 * results the columns are for.
 */
/**
 * What an export leaves out, when there is something it leaves out.
 *
 * A probabilistic result is drawn over the deterministic one -- the chart
 * swaps the line for the median of the realisations and puts the spread behind
 * it -- but an export writes `state.results`, which is the deterministic run.
 * So the file and the picture disagree, and nothing on screen said so: the
 * numbers look like the ones that were being looked at and are not.
 *
 * Saying it in the same notice that reports the export is the smallest honest
 * version of this. Writing the realisations themselves is a larger job and not
 * done yet -- see README, *A probabilistic run*.
 */
function exportCaveat() {
	return currentProb()
		? ' These are the deterministic values, not the realisations.'
		: '';
}

/**
 * The probabilistic run, if it is still a run of the model on screen.
 *
 * `state.prob` outlives the run that made it on purpose -- the matrix stays in
 * the worker and is fetched when an export asks for it -- but it must not
 * outlive the *model*. It used to: nothing cleared it, not even opening a
 * different file, so the bands of one model were drawn under the lines of the
 * next wherever two series happened to share a label, the export wrote one
 * model's realisations beside another's columns, and *What drove it* offered
 * an answer about a model that was no longer there. None of that looks wrong
 * on the screen, which is what made it worth a single gate rather than a
 * check at each of the seven places that read it.
 *
 * The test is the revision, not the run id: a run id moves whenever anything
 * is run, including a re-solve of the very same model, and bands that still
 * describe the model in front of you should survive that.
 */
/**
 * The three lines the time chart can draw through a sample, in the order they
 * are offered and drawn.
 *
 * `set` is the dash pattern each wears when more than one is up -- solid for
 * the median, long dashes for the mean, dots for the model's own run -- while
 * the colour stays the output's. Colour is which series this is; the pattern
 * is which line of it.
 */
const CHART_LINES = [
	{ key: 'median', name: 'median', set: 0 },
	{ key: 'mean', name: 'mean', set: 1 },
	{ key: 'single', name: 'own run', set: 2 },
];

/** Which of them are on, in that order. Never empty. */
function linesOn() {
	const on = CHART_LINES.filter((l) => state.chartLines[l.key]);
	return on.length ? on : [CHART_LINES[0]];
}

function currentProb() {
	return probIsCurrent(state.prob, state.results, state.rev, state.probRunning)
		? state.prob
		: null;
}

/**
 * Series `k`'s band, over the sample's times.
 *
 * A varied parameter's arrives as one number per statistic -- `flat`, see
 * `bandsOf` in ../worker/sim-worker.js -- and is spread across the times the
 * first time something draws it, then kept with the band: a chart of three
 * parameters has no use for the other thousand spread out.
 */
export function bandOf(prob, k) {
	const band = prob?.bands?.[k] ?? null;
	if (!band?.flat) return band;
	if (!band.spread) {
		const times = prob.t?.length ?? 1;
		const along = (v) => {
			if (!v || v.length === times) return v;
			const out = new v.constructor(times);
			out.fill(v[0]);
			return out;
		};
		band.spread = {
			flat: true,
			q: band.q.map(along),
			mean: along(band.mean),
			sd: band.sd ? { sd: along(band.sd.sd), n: along(band.sd.n) } : band.sd,
			med: band.med ? {
				errLo: along(band.med.errLo), errHi: along(band.med.errHi),
				bodyLo: along(band.med.bodyLo), bodyHi: along(band.med.bodyHi),
			} : band.med,
		};
	}
	return band.spread;
}

/**
 * What a sample holds, by block and by series.
 *
 * `blocks` maps a block's qualified name to `kept` -- an endpoint the run kept
 * the realisations of -- or `varied` -- a parameter it varied, held as the
 * values drawn; `labels` does the same by series label. A far-field path's
 * results are named by the run (`Rock held`, `Rock.gravel1`) rather than after
 * a block, and count for the block at the front of the name: the rule
 * `ed.endpoints` reads a list by.
 *
 * @param {{outputs: Array<{block?: string, label: string, varied?: boolean}>}} prob
 * @param {Iterable<string>} names  the model's blocks, by qualified name
 */
export function sampleContents(prob, names) {
	const known = new Set(names);
	const blockOf = (name) => {
		if (known.has(name)) return name;
		for (const cut of [name.lastIndexOf(' '), name.lastIndexOf('.')]) {
			if (cut > 0 && known.has(name.slice(0, cut))) return name.slice(0, cut);
		}
		return null;
	};
	const blocks = new Map();
	const labels = new Map();
	for (const o of prob?.outputs ?? []) {
		const which = o.varied ? 'varied' : 'kept';
		labels.set(o.label, which);
		const b = blockOf(o.block ?? o.label ?? '');
		if (b && !blocks.has(b)) blocks.set(b, which);
	}
	return { blocks, labels };
}

/** `sampleContents` of the sample on screen, worked out once per sample; null with none. */
let sampleHeld = null;
function sampleHolds() {
	const prob = currentProb();
	if (!prob) return null;
	if (sampleHeld?.prob !== prob) {
		sampleHeld = { prob, ...sampleContents(prob, ed.allBlocks(state.raw).map((b) => ed.qualifiedName(b))) };
	}
	return sampleHeld;
}

/**
 * The tree's filter as it stands: the search, and -- with the Probabilistic
 * chip on and a sample to be about -- only the blocks the sample holds, on top
 * of a pinned answer where there is one. With no sample the chip is not
 * there and asks for nothing.
 */
function treeFilter() {
	const f = state.search;
	const held = f.sample ? sampleHolds() : null;
	if (!held) return f;
	return { ...f, only: f.only ? f.only.filter((n) => held.blocks.has(n)) : [...held.blocks.keys()] };
}

/**
 * The rule `currentProb` applies, on its own so it can be tested.
 *
 * Against the **model**, first: a sample is a sample of the distributions it
 * was drawn from, so widening a spread or changing a shape makes every one of
 * its realisations a realisation of a model that no longer exists. Judged
 * against the results alone, an edit that left the deterministic run equally
 * stale kept the sample alive beside it -- the bands, the line in the corner
 * saying what had run, and *What drove it…* all went on describing
 * distributions the reader had already replaced.
 *
 * And against the results on screen where there are any -- those are what the
 * bands would be drawn beside, and a band belongs under its own line or under
 * none.
 *
 * @param {object|null} prob     the probabilistic result, with its `rev`
 * @param {object|null} results  the deterministic results on screen
 * @param {number} rev           the model's revision now
 * @param {boolean} running      whether a probabilistic run is in flight
 */
export function probIsCurrent(prob, results, rev, running = false) {
	if (!prob || running) return false;
	if (prob.rev !== rev) return false;
	return !results || prob.rev === results.rev;
}

/**
 * Which series *What drove it* is about.
 *
 * Three cases, and the third is the one worth writing down.
 *
 * An explicit `index` wins: that is the dialog's own *Of* picker asking again,
 * and it can only offer what the run kept. With none, the series is the first
 * line on the chart -- the one in front of the reader, which is what they mean
 * by "it".
 *
 * And when that line is not one the run kept -- *Keep only the N endpoints* was
 * ticked and this is not one of them -- it falls back to the first series that
 * *was* kept, saying so. It used to refuse: a warning, and no dialog. That was
 * the right answer when there was no way to choose a different series, and the
 * wrong one now that the dialog opens with a picker: the answer the reader
 * wanted is one control away rather than three steps back.
 *
 * A varied parameter is not one of the series asked about unless `inputs`
 * says so: *What drove it* of an input is that input, and its list would be
 * every input over again. A distribution of one is worth seeing, so that
 * dialog does ask. They come after the kept series (`withInputs` in
 * ../worker/sim-worker.js), so leaving them out leaves every index as it was.
 *
 * @param {object} prob        the probabilistic result
 * @param {object|null} results  the deterministic results, for the labels
 * @param {number[]} selected  which of those are charted
 * @param {number|null} index  an explicit choice, from the picker
 * @param {boolean} [inputs]   whether a varied parameter can be the answer
 * @returns {{index: number, fellBack: boolean}|null} null when there is
 *   nothing to ask about at all
 */
export function sensitivityTarget(prob, results, selected = [], index = null, inputs = false) {
	const kept = (prob?.outputs ?? []).filter((o) => inputs || !o.varied);
	if (!kept.length) return null;
	if (index != null) {
		// Clamped rather than trusted: the picker is built from this same list,
		// but a stale index is a wrong answer under a right-looking title.
		const k = Math.min(kept.length - 1, Math.max(0, Math.round(index)));
		return { index: k, fellBack: false };
	}
	const label = selected.length
		? results?.outputs?.[selected[0]]?.label
		: kept[0].label;
	const found = kept.findIndex((o) => o.label === label);
	return found < 0 ? { index: 0, fellBack: true } : { index: found, fellBack: false };
}

export function messageIsCurrent(m, runId) {
	// `sensitivity` joins `columns` and `prob-matrix` for the same reason: it
	// is an answer about the *probabilistic* run, which keeps its own id, and
	// any run since has moved `state.runId` past it. Dropped here, the reply
	// to a question the reader had just asked went nowhere at all.
	return PROB_REPLIES.has(m.type) || OWN_ID_REPLIES.has(m.type)
		|| m.type === 'columns' || m.type === 'dataset'
		|| m.id === runId;
}

/**
 * Every reply that is about the *probabilistic* run rather than the current
 * one, and so carries the sample's id and not `state.runId`.
 *
 * A set rather than a chain of comparisons because this list is the trap: a new
 * question about the sample is answered under the sample's id, `state.runId`
 * has moved past it by then -- a deterministic run, an auto-run, anything --
 * and a reply that is not named here is dropped by the line above with nothing
 * said. The symptom is a panel that waits for ever, which is how `prob-hist`
 * was found.
 */
/**
 * Replies that carry an id of their *own* counter rather than a run's.
 *
 * The same trap as `PROB_REPLIES` and a different counter: an optimisation
 * numbers its own questions, so `m.id` is never `state.runId` and the line
 * above would drop every answer with nothing said -- a dialog that runs for a
 * minute and then waits for ever.
 */
const OWN_ID_REPLIES = new Set(['optimise', 'optimise-progress', 'variables']);

const PROB_REPLIES = new Set([
	'prob-matrix', 'prob-bands', 'prob-categories', 'prob-summary', 'prob-hist',
	'prob-points', 'sensitivity', 'tornado', 'tornado-table', 'gsa', 'gsa-table',
]);

function ensureWorker() {
	if (worker) return worker;
	worker = new Worker(
		new URL('../worker/sim-worker.js', import.meta.url), { type: 'module' },
	);
	worker.onmessage = (ev) => {
		const m = ev.data;
		if (!messageIsCurrent(m, state.runId)) return;
		if (m.type === 'loading') { setLoadingStage(m.stage, m.detail); return; }
		if (m.type === 'pool') { acceptPool(m); return; }
		if (m.type === 'progress') {
			// The Jacobian check reports its progress too, and it is not a run:
			// it has no chart to fill and no footer statistics, so it draws its
			// own bar rather than moving the run's.
			if (generated.busy === 'check') {
				generated.progress = m.fraction;
				if (state.tab === 'code' && generated.view === 'jacobian') renderJacobian();
				return;
			}
			// A sampled run says how many of how many realisations are in,
			// which is what the time it has left is worked out from.
			if (m.of) noteRealisations(m.realisation, m.of);
			setProgress(m.fraction, m.at);
			return;
		}
		if (m.type === 'done') { acceptResults(m.payload, m.replayed ?? null, m.log ?? null); return; }
		if (m.type === 'prob-bands') { acceptProbBands(m); return; }
		if (m.type === 'prob-categories') { acceptCategories(m); return; }
		if (m.type === 'prob-summary') { acceptSummary(m); return; }
		if (m.type === 'tornado') { acceptTornado(m); return; }
		if (m.type === 'tornado-table') { acceptTornadoTable(m); return; }
		if (m.type === 'gsa') { acceptGsa(m); return; }
		if (m.type === 'gsa-table') { acceptGsaTable(m); return; }
		if (m.type === 'probabilistic-done') { acceptProbabilistic(m.payload, m.id); return; }
		if (m.type === 'prob-matrix') { acceptProbMatrix(m); return; }
		if (m.type === 'variables') { acceptVariables(m); return; }
		if (m.type === 'optimise-progress') { state.optOpen?.progress(m); return; }
		if (m.type === 'optimise') {
			if (m.ok) state.optOpen?.finished(m.result);
			else state.optOpen?.failed(m.message ?? 'It could not be solved.');
			return;
		}
		if (m.type === 'prob-hist') { acceptHistograms(m); return; }
		if (m.type === 'prob-points') { acceptPoints(m); return; }
		if (m.type === 'reused') { acceptReuseRefused(m); return; }
		if (m.type === 'sensitivity') { acceptSensitivity(m); return; }
		if (m.type === 'jacobian-pattern') { acceptJacobianPattern(m); return; }
		if (m.type === 'jacobian-check') { acceptJacobianCheck(m); return; }
		if (m.type === 'local-sensitivity') { acceptLocalSensitivity(m); return; }
		if (m.type === 'columns') { acceptColumns(m); return; }
		if (m.type === 'dataset') { datasetWaiting?.(m); return; }
		// The selected scenario failing is the model failing: the scenarios
		// beside it are the same model, and are stopped rather than left to
		// fail one by one.
		if (m.type === 'error') { stopScenarios(); setRunning(false); showError(m); }
	};
	worker.onerror = (e) => {
		stopScenarios();
		setRunning(false);
		showError({ name: 'WorkerError', message: e.message ?? 'The simulation worker failed.' });
		// A worker that has failed is not one to post the next run to: left
		// installed, every Run after a module that would not link went into
		// the void and the interface sat lit with nothing coming. Replaced
		// on the next `ensureWorker`, exactly as Stop does it.
		detachResults();
		worker.terminate();
		worker = null;
	};
	return worker;
}

/**
 * Whoever is waiting for the worker to hand over the run as bytes.
 *
 * One at a time: Save is a dialog and a write, and a second Save started while
 * the first is still marshalling eighty megabytes is a thing to refuse rather
 * than to queue.
 */
let datasetWaiting = null;

/**
 * The current run as the parts of a results archive.
 *
 * The states are in the worker, so this is a round trip -- and the buffers come
 * back transferred rather than copied, which on a large model is the difference
 * between one eighty-megabyte allocation and two.
 *
 * @returns {Promise<Array<{name: string, bytes: Uint8Array}>>}
 */
function requestDataset(inner) {
	if (state.results?.local) {
		// No worker in this run: the results are right here, so the file can be
		// written without asking anybody. `?mainthread`, or a browser with no
		// Worker.
		return import('../io/dataset.js').then(({ datasetEntries }) => datasetEntries({
			project: state.raw,
			results: state.results.local.results,
			inner,
			stamp: new Date().toISOString(),
			log: runLogFor().split('\n'),
		}));
	}
	if (!worker || state.results?.detached) {
		return Promise.reject(new Error('The run that produced these results is no '
			+ 'longer being held — the worker was stopped or replaced. Run it again '
			+ 'and save from that.'));
	}
	if (datasetWaiting) {
		return Promise.reject(new Error('A save is already in progress.'));
	}
	return new Promise((resolve, reject) => {
		const timer = setTimeout(() => {
			datasetWaiting = null;
			reject(new Error('The worker did not answer in time.'));
		}, DATASET_WAIT);
		datasetWaiting = (m) => {
			clearTimeout(timer);
			datasetWaiting = null;
			if (m.ok) resolve(m.parts);
			else reject(new Error(m.why ?? 'The run could not be written out.'));
		};
		worker.postMessage({
			type: 'dataset',
			id: state.results.runId,
			project: state.raw,
			inner,
			stamp: new Date().toISOString(),
			// The run's own account, so an archive says what it is without
			// this page: which solver, which tolerances, what was held.
			log: runLogFor().split('\n'),
		});
	});
}

/** Long enough for a landscape model's eighty megabytes, short enough to end. */
const DATASET_WAIT = 120000;

/**
 * Notes that the worker holding the results' states is gone, so no more
 * columns can be asked of it. The results stay on screen -- they are right
 * -- but a series not yet fetched has nowhere to come from now.
 */
function detachResults() {
	if (state.results && !state.results.local) state.results.detached = true;
}

/**
 * @param {{manual?: boolean}} [opts] `manual` for a press of Run or Cmd-Enter,
 *   as against the auto-run timer -- the difference being whether a refusal is
 *   worth saying out loud.
 */
function runSimulation(opts = {}) {
	// Remembered, and whether it was asked for by hand: Cmd-Enter during a
	// long run with auto-run off used to be forgotten the moment the run
	// ended, since only the timer's wish was honoured.
	if (state.running) {
		runWanted = true;
		if (opts.manual) runWantedManual = true;
		return;
	}
	// Asked for by hand, with one of the sample's pictures up: the reader has
	// pressed *Run once* and is waiting to see what one run gives, so the tab
	// goes back to the curves and draws that run rather than the thousand
	// behind it. The sample is kept -- it is still a sample of this model, and
	// throwing away a thousand integrations because somebody wanted to see one
	// is not a trade anybody would choose -- and one turn of the control
	// brings it back.
	if (opts.manual && showingSample()) {
		state.chartMode = 'time';
		// Turned on, not switched to: the three lines can be up together, and
		// silently clearing the reader's other two to show this one would be
		// answering a question they did not ask.
		state.chartLines = { ...state.chartLines, single: true };
	}
	// A model the scan has already objected to is not handed to the solver.
	// It would fail in the same way and say so a second time in slightly
	// different words -- `Project` says "greater than zero (got 0)" where the
	// scan says "greater than zero" -- and two lines for one mistake makes the
	// reader look for a second mistake.
	if (state.problems.length) {
		clearTimeout(autoRunTimer);
		autoRunTimer = null;
		renderStaleness();
		if (opts.manual) {
			flash(state.problems.length === 1
				? 'The model has a problem that has to be fixed before it can run.'
				: `The model has ${state.problems.length} problems that have to be `
					+ 'fixed before it can run.', 'warn');
		}
		return;
	}
	// A preview runs against a *copy* with other values in it, which is how
	// "show me what these give" can be answered without editing anything. Any
	// ordinary run clears it: the next thing the reader asks for is about the
	// model, not about the preview.
	if (!opts.substitute) state.preview = null;
	let project;
	try {
		const raw = opts.substitute
			? (() => { const copy = structuredClone(state.raw); putValues(copy, opts.substitute); return copy; })()
			: state.raw;
		project = new Project(structuredClone(raw));
		state.project = project;
		// What the run will produce, for the progress bar to count against.
		// Worked out once here rather than per report: on a series grid it is
		// a few hundred numbers, and the bar is told a clock forty times a
		// second. A two-point grid -- the solver's own steps -- says nothing
		// about how far along a run is, so `setProgress` keeps the fraction.
		state.grid = project.timeGrid();
		state.gridAt = 0;
	} catch (e) {
		clearTimeout(autoRunTimer);
		autoRunTimer = null;
		showError({ name: e.name, message: e.message, blockName: e.blockName });
		return;
	}
	clearError();
	setRunning(true);
	state.primaryBusy = true;
	state.runId += 1;
	// Which model this run is of. Stamped onto the results when they arrive.
	state.runRev = state.rev;
	state.runSolver = project.simulation?.solver ?? DEFAULT_SOLVER;
	state.runKey = integrationKeyNow(project);
	clearTimeout(autoRunTimer);
	autoRunTimer = null;

	if (workerAvailable()) {
		// Solved again, or only worked out again. Every expression is computed
		// from `(t, y)` when it is asked for, so a model whose integrating part
		// has not changed still has its states: what is out of date is the
		// algebra over them, and that is a rebuild without a single step. The
		// worker checks the state layout before it trusts this and says so if
		// it will not.
		const key = state.integrationKey;
		const reuse = !!key && !!state.results && !state.results.detached
			&& key === state.runKey;
		state.reusing = reuse;
		ensureWorker().postMessage({
			type: reuse ? 're-evaluate' : 'run',
			id: state.runId,
			project: project.toJSON(),
			// The cores this run may split its model over, if it does: see
			// `splitShare`.
			cores: splitShare(),
			workers: workerLimit(),
		});
		// And the scenarios chosen to run beside this one, each in a worker of
		// its own. Not for a preview: that is this scenario at values the model
		// does not hold, and a line of another scenario at the values it does
		// would be drawn beside it as if the two were comparable.
		if (opts.substitute) stopScenarios({ all: true });
		else startScenarios();
	} else {
		state.reusing = false;
		// One thread, so one run: the scenarios beside it need workers.
		if (otherScenarios(state.raw, state.scenarioChoice).length && !runSimulation.saidMainThread) {
			runSimulation.saidMainThread = true;
			flash('Only the selected scenario runs here: running several at once needs '
				+ 'the browser\u2019s workers, which this page is not using.', 'warn');
		}
		runOnMainThread(project, state.runId);
	}
}

// --- scenarios run together ------------------------------------------------------

/**
 * The runs of the scenarios beside the selected one that belong with the
 * results on screen: finished, of the model revision those results are of, and
 * -- unless `hidden` is false -- not switched off in the legend. In the
 * model's scenario order. None beside a replayed realisation or a preview,
 * which are not the model at its own values, while every scenario's run is.
 */
function shownScenarioRuns({ hidden = true } = {}) {
	const r = state.results;
	if (!r || r.replayed != null || state.preview) return [];
	const out = [];
	for (const name of otherScenarios(state.raw, state.scenarioChoice)) {
		const e = state.scenarioRuns.get(name);
		if (!e?.r || e.r.rev !== r.rev) continue;
		if (hidden && state.hiddenScenarios.has(name)) continue;
		out.push(e);
	}
	return out;
}

/**
 * The scenario runs the chart draws: those of `shownScenarioRuns`, while the
 * chart's line is the model's own run. Through a sample the line is a median
 * or a mean of realisations, and a scenario's deterministic run beside it
 * would be a different kind of number drawn as if it were the same one; the
 * table and the exports, which are of the runs, still carry them.
 */
function chartScenarioRuns(opts = {}) {
	if (currentProb()) {
		const keys = linesOn().map((l) => l.key);
		if (!(keys.length === 1 && keys[0] === 'single')) return [];
	}
	return shownScenarioRuns(opts);
}

/** The runs of the scenarios chosen beside the selected one, in the model's order. */
function scenarioRunsNow() {
	return otherScenarios(state.raw, state.scenarioChoice)
		.map((name) => state.scenarioRuns.get(name) ?? { name, r: null });
}

/** Whether a scenario beside the selected one is running, or waiting to. */
function scenariosBusy() {
	for (const e of state.scenarioRuns.values()) if (e.running || e.queued) return true;
	return false;
}

/**
 * A worker of its own for one scenario, answering to that scenario's entry.
 *
 * The same simulation worker the selected scenario runs in, asked the same
 * things -- `run`, `re-evaluate`, `columns` -- so a scenario's results are
 * held and read exactly as the selected one's are, in the worker that made
 * them.
 */
function scenarioWorker(entry) {
	const w = new Worker(new URL('../worker/sim-worker.js', import.meta.url), { type: 'module' });
	w.onmessage = (ev) => acceptScenarioMessage(entry, ev.data);
	w.onerror = (e) => {
		if (entry.worker === w) entry.worker = null;
		if (entry.r) entry.r.detached = true;
		try { w.terminate(); } catch { /* it has failed; this is tidying */ }
		failScenario(entry, e.message ?? 'its worker failed');
	};
	return w;
}

function acceptScenarioMessage(entry, m) {
	// A scenario that has been dropped since its worker was asked.
	if (state.scenarioRuns.get(entry.name) !== entry) return;
	if (m.type === 'columns') { acceptScenarioColumns(entry, m); return; }
	if (m.id !== entry.runId) return;
	if (m.type === 'loading') { entry.stage = m.stage; paintProgress(); return; }
	if (m.type === 'progress') {
		entry.fraction = gridFraction(entry, m.fraction, m.at);
		paintProgress();
		return;
	}
	if (m.type === 'done') { acceptScenario(entry, m.payload); return; }
	if (m.type === 'reused') {
		// Refused, as `acceptReuseRefused` is for the selected scenario: the
		// states moved after all, so it is solved.
		if (m.ok) return;
		entry.key = null;
		entry.nextKey = null;
		entry.worker?.postMessage({
			type: 'run', id: entry.runId, project: entry.project,
			cores: splitShare(), workers: workerLimit(),
		});
		return;
	}
	if (m.type === 'error') failScenario(entry, m.message ?? 'it failed');
}

/**
 * Queues every chosen scenario for the run that has just started, and lets go
 * of the ones no longer chosen.
 */
function startScenarios() {
	const want = otherScenarios(state.raw, state.scenarioChoice);
	for (const name of [...state.scenarioRuns.keys()]) if (!want.includes(name)) dropScenario(name);
	for (const name of want) queueScenario(name);
	pumpScenarios();
}

/**
 * Makes scenario `name` ready to run as part of the run now in progress.
 *
 * Worked out again or solved again, like the selected scenario: a scenario
 * whose integrating part has not changed since its last run keeps its states
 * and has only the algebra over them worked out afresh (`re-evaluate`), which
 * its worker checks before it trusts.
 */
function queueScenario(name) {
	let entry = state.scenarioRuns.get(name);
	if (!entry) {
		entry = { name, worker: null, r: null, key: null };
		state.scenarioRuns.set(name, entry);
	}
	// A run of it still going is of a model that has since changed, and a
	// solve is not interrupted by a message: the worker goes with it.
	if (entry.running && entry.worker) {
		try { entry.worker.terminate(); } catch { /* gone already */ }
		entry.worker = null;
		if (entry.r) entry.r.detached = true;
	}
	let project;
	try {
		project = new Project(scenarioModel(state.raw, name));
	} catch (e) {
		entry.queued = false;
		entry.running = false;
		entry.error = e.message ?? String(e);
		return;
	}
	const key = integrationKeyNow(project);
	entry.project = project.toJSON();
	entry.nextKey = key;
	entry.reuse = !!key && key === entry.key && !!entry.r && !entry.r.detached && !!entry.worker;
	entry.runId = state.runId;
	entry.rev = state.runRev;
	entry.queued = true;
	entry.running = false;
	entry.fraction = 0;
	entry.gridAt = 0;
	entry.stage = null;
	entry.error = null;
}

/**
 * Starts as many of the waiting scenarios as there are cores for. The
 * selected scenario counts while it is running; the rest start as others
 * finish. See `runsAtOnce`.
 */
function pumpScenarios() {
	const most = runsAtOnce(chosenCores(), machineCores());
	let going = (state.primaryBusy ? 1 : 0)
		+ [...state.scenarioRuns.values()].filter((e) => e.running).length;
	for (const name of otherScenarios(state.raw, state.scenarioChoice)) {
		if (going >= most) break;
		const entry = state.scenarioRuns.get(name);
		if (!entry?.queued) continue;
		entry.queued = false;
		entry.running = true;
		going++;
		try {
			entry.worker ??= scenarioWorker(entry);
		} catch (e) {
			failScenario(entry, e.message ?? String(e));
			continue;
		}
		entry.worker.postMessage({
			type: entry.reuse ? 're-evaluate' : 'run', id: entry.runId, project: entry.project,
			cores: splitShare(), workers: workerLimit(),
		});
	}
}

/**
 * How many cores one run may split its model over: the cores a run of the
 * page may have, shared between the runs going at once -- the selected
 * scenario and those beside it -- so that several scenarios each divided into
 * parts do not ask for more threads than the machine has. See `splitWorkers`
 * in ../worker/sim-worker.js, which reads it.
 */
function splitShare() {
	const most = runsAtOnce(chosenCores(), machineCores());
	const runs = Math.min(most, 1 + otherScenarios(state.raw, state.scenarioChoice).length);
	return Math.max(1, Math.floor(most / Math.max(1, runs)));
}

/** A scenario's run is in. */
function acceptScenario(entry, payload) {
	entry.running = false;
	entry.key = entry.nextKey ?? null;
	entry.error = null;
	entry.r = {
		...payload, columns: [], rev: entry.rev, runId: entry.runId,
		scenario: entry.name, worker: entry.worker,
	};
	pumpScenarios();
	finishIfDone();
	renderPicker();
	renderChart();
	renderTable();
	refreshStatus();
}

/** A scenario's run failed. Said, and the rest carry on without it. */
function failScenario(entry, why) {
	entry.running = false;
	entry.queued = false;
	entry.error = why;
	flash(`The scenario \u2018${entry.name}\u2019 did not run: ${why}`, 'warn');
	pumpScenarios();
	finishIfDone();
	refreshStatus();
}

/** Lets go of one scenario's run: its worker, and the results it held. */
function dropScenario(name) {
	const e = state.scenarioRuns.get(name);
	if (!e) return;
	state.scenarioRuns.delete(name);
	try { e.worker?.terminate(); } catch { /* gone already */ }
}

/**
 * Stops the scenarios still running or waiting -- Stop, or the selected
 * scenario failing, which says the model does not run. The ones already in
 * are kept, unless `all`.
 */
function stopScenarios({ all = false } = {}) {
	for (const [name, e] of [...state.scenarioRuns]) {
		if (all || e.running || e.queued) dropScenario(name);
	}
}

/** Ends the run once the selected scenario and every one beside it are in. */
function finishIfDone() {
	if (state.running && !state.primaryBusy && !scenariosBusy()) {
		setRunning(false);
		renderStaleness();
		return;
	}
	paintProgress();
}

/**
 * The reader has ticked or unticked a scenario to run beside the selected one.
 *
 * Unticked, its run goes. Ticked, it is run now if the results on screen are
 * of the model as it stands, so the comparison is there without running the
 * others again; otherwise it waits for the next run, which is due anyway.
 */
function chooseScenario(name, on) {
	const was = new Set(state.scenarioChoice);
	if (on) was.add(name); else was.delete(name);
	state.scenarioChoice = scenariosToRun(state.raw, was);
	if (!on) {
		dropScenario(name);
		state.hiddenScenarios.delete(name);
		finishIfDone();
	} else if (workerAvailable() && !state.preview) {
		const batch = state.running && (state.primaryBusy || scenariosBusy());
		if (batch && state.runRev === state.rev) {
			// Into the run that is going: the model has not moved since it
			// started, so this scenario is of the same model as the rest.
			queueScenario(name);
			pumpScenarios();
		} else if (!state.running && state.results && state.results.rev === state.rev
			&& !state.results.detached && state.results.replayed == null) {
			// A run of its own, beside the results already on screen and
			// under their id, so that it is drawn with them -- which leaves
			// the status line about them standing.
			setRunning(true, { keepStatus: true });
			queueScenario(name);
			const entry = state.scenarioRuns.get(name);
			if (entry) { entry.runId = state.results.runId; entry.rev = state.results.rev; }
			pumpScenarios();
			finishIfDone();
		}
		// Otherwise the run that is owed -- the model has changed since the
		// results on screen -- takes it with the rest.
	}
	renderSidebar();
	// Back to the chip, which the rebuild replaced: the keyboard would
	// otherwise be dropped on the page after every press.
	[...document.querySelectorAll('#sidebar [data-scenario-run]')]
		.find((b) => b.dataset.scenarioRun === name)?.focus();
	renderChart();
	renderTable();
	refreshStatus();
}

/**
 * The share of a scenario's run that is done, read off the output grid the
 * way the selected scenario's is: points reached, not model time. See
 * `setProgress`.
 */
function gridFraction(entry, fraction, at) {
	const grid = state.grid;
	if (grid && grid.length > 2 && at != null && Number.isFinite(at)) {
		while (entry.gridAt < grid.length && grid[entry.gridAt] <= at) entry.gridAt++;
		return entry.gridAt / grid.length;
	}
	return Math.max(0, Math.min(1, fraction));
}

/**
 * The fingerprint of what this model's states are a function of.
 *
 * Computed from the `Project` rather than the raw model, so that the two sides
 * of a comparison have been through the same normalisation -- an entry folded
 * out of `values_by_nuclide` has to look the same as one written by hand, or
 * every import would appear to be a different model from itself.
 *
 * Wrapped because it can throw: a model mid-edit may not normalise at all, and
 * an unanswerable question here is answered "it changed", which costs a solve
 * and is never wrong.
 */
function integrationKeyNow(project) {
	try {
		return ed.integrationFingerprint(project);
	} catch {
		return null;
	}
}

async function runOnMainThread(project, id) {
	await new Promise((r) => setTimeout(r, 0));
	try {
		const { run } = await import('../sim/runner.js');
		// Same wait the worker does, for the same reason. Without it the
		// fallback path -- ?mainthread, or a browser with no Worker -- would be
		// the one place a SciPy solver failed with "the runtime has not been
		// loaded" and no way to load it.
		const { isScipySolver, loadScipy, scipyReady } = await import('../ode/scipy.js');
		if (isScipySolver(project.simulation?.solver) && !scipyReady()) {
			await loadScipy({ onProgress: setLoadingStage });
			if (id !== state.runId) return;
		}
		const results = run(project.toJSON());
		if (id !== state.runId) return;
		const outputs = results.outputs();
		acceptResults({
			t: results.t,
			outputs: outputs.map((o) => ({
				kind: o.kind, block: o.block, nuclide: o.nuclide,
				// dims and index carry which index combination this line is,
				// which is what the chart's filters select on.
				dims: o.dims ?? [], index: o.index ?? null,
				label: o.label, unit: o.unit,
				constant: results.constantOf(o),
			})),
			// No columns: with the results in this thread, `column` works a
			// series out from them the moment it is asked for.
			columns: [],
			local: { results, outputs },
			stats: results.stats,
			timing: results.timing,
			nuclides: results.nuclides,
			generatedSource: results.system.source,
			stateCount: results.system.layout.nstate,
			jacobian: results.jacobian,
			heldAtZero: results.heldAtZero(),
		});
	} catch (e) {
		showError({
			name: e.name ?? 'Error', message: e.message ?? String(e),
			blockName: e.blockName ?? null, hint: e.hint ?? null,
		});
		setRunning(false);
	}
}

function acceptResults(payload, replayed = null, storedLog = null) {
	// The revision these belong to, taken when the run was launched rather
	// than now: an edit made while the solver was working must not be able to
	// pass itself off as included in the answer.
	// And the run they came from, for the columns asked of the worker later:
	// asked under the *current* run's id, a column requested while the next
	// run was in flight was answered from that run's results, or -- after a
	// Stop, which terminates the worker -- not at all, and never asked again.
	// `replayed` says these are one realisation of a probabilistic run, run
	// again in full -- which the status line says, since a curve that is the
	// 734th draw and not the model's values is a different thing to read.
	state.results = { ...payload, rev: state.runRev ?? state.rev, runId: state.runId, replayed, storedLog };
	// What this run warns about, in place of the last run's: see `runWarnings`.
	const hadWarnings = state.runWarnings.length > 0;
	state.runWarnings = Array.isArray(payload.stats?.farfield) ? payload.stats.farfield : [];
	if (hadWarnings || state.runWarnings.length) remark();
	// What the next edit will be compared against. Taken from the model this
	// run was of, not the one on screen, for the same reason `rev` is.
	state.integrationKey = state.runKey ?? null;
	state.lastSolveMs = payload.timing.solveMs;
	state.lastSolveSolver = state.runSolver ?? null;
	state.dirty = state.results.rev !== state.rev;
	reconcileSelection();
	renderResults();
	setStatus(payload);
	clearError();
	// In, but the run is not over while a scenario beside it is still going:
	// that one's slot passes to a scenario waiting for a core, and the
	// interface stays in its running state until the last is in.
	state.primaryBusy = false;
	pumpScenarios();
	finishIfDone();
	updateDirtyBadge();
	renderStaleness();
}

/** The status line again, for a scenario that has come in beside the results. */
function refreshStatus() {
	if (state.results) setStatus(state.results);
}

/**
 * Asks what a probabilistic run should do, then does it.
 *
 * The plan is worked out on the page rather than in the worker because the
 * dialog needs it before anything is started -- how many values would be
 * drawn, and from what. On a large model that is a build, which is why the
 * dialog is opened from a button and not from a hover.
 */
/**
 * How many series the model's endpoint list comes to, or null.
 *
 * Needs a run to answer: an endpoint is a block, and how many series a block is
 * depends on the index lists it carries, which is a fact about the built
 * system rather than the file. With no results yet the dialog falls back to
 * counting the endpoints, which is right for a model with no index lists and
 * an under-estimate otherwise -- it said 305 MB for a run the worker then
 * refused at 1.2 GB, because `Dose` is four series and not one.
 */
/**
 * Every series this model would report, whether or not it has been run.
 *
 * A run's own outputs where there is one; otherwise the same list worked out
 * from the layout, which exists as soon as the model builds. That is what lets
 * the endpoint picker and the cost line in the probabilistic dialog say
 * anything at all before a run -- and saying it before is the point, since
 * choosing endpoints is how a run is stopped from keeping 831,314 series.
 *
 * Cached against the model's revision: building is the expensive half (a
 * couple of seconds on a landscape model), and both callers ask on every
 * redraw of their dialog. A model that will not build answers null, which is
 * the same answer as "not run yet" and is handled the same way.
 */
let builtOutputs = { rev: -1, outputs: null };
function outputsNow() {
	if (state.results?.outputs?.length) return state.results.outputs;
	if (builtOutputs.rev === state.rev) return builtOutputs.outputs;
	let outputs = null;
	try {
		const project = new Project(structuredClone(state.raw));
		outputs = outputsOf(buildSystem(project), project);
	} catch {
		// Not reported here: this is called to fill in a number, and the two
		// dialogs that call it say their own piece about a model that will not
		// build.
		outputs = null;
	}
	builtOutputs = { rev: state.rev, outputs };
	return outputs;
}

function endpointSeriesCount() {
	const outs = outputsNow();
	if (!outs?.length) return null;
	const want = new Set(ed.endpoints(state.raw));
	if (!want.size) return null;
	let n = 0;
	for (const o of outs) if (want.has(o.block ?? o.label ?? '')) n++;
	return n;
}

function openProbabilistic() {
	if (state.running) { flash('A run is already going. Stop it first.', 'warn'); return; }
	let plan;
	try {
		plan = samplingPlan(new Project(structuredClone(state.raw)));
	} catch (e) {
		showError({ name: e.name ?? 'Error', message: e.message, blockName: e.blockName ?? null });
		flash(`A probabilistic run needs a model that builds. ${e.message}`, 'warn');
		return;
	}
	// A model whose only dice are disruptive events still has realisations
	// to run: `hasDistributions` counts those, as the button above does.
	if (!plan.length && !ed.hasDistributions(state.raw)) {
		flash('No parameter in this model has a distribution to sample.', 'warn');
		return;
	}
	openProbabilisticDialog({
		plan,
		// Only where there is one to throw away.
		onDiscard: currentProb() ? () => discardProb() : null,
		simulation: state.raw.simulation ?? {},
		// What one run produces, from the run that has already happened where
		// there is one: this is a question about the model, not about the
		// distributions, so a deterministic result answers it exactly. Less
		// the parameters, which a sample never holds as curves: the ones it
		// varies are kept as their draws, and the rest do not vary.
		series: (outputsNow() ?? []).filter((o) => ed.canBeEndpoint(o.kind)).length,
		// The times, though, are the grid's and not that run's: every
		// realisation is reported on the grid (runProbabilistic), and a run
		// that also keeps the solver's own points has many more. Counting
		// those put a large sample at ten times what the run would hold, and
		// refused a run that fits.
		times: timesOfModel().length,
		lastSolveMs: state.lastSolveMs || null,
		endpoints: ed.endpoints(state.raw),
		// What those endpoints come to in series, which is what decides the
		// size: they are block names, and a block indexed by four nuclides is
		// four of them.
		endpointSeries: endpointSeriesCount(),
		// What the worker will do with it, worked out the same way it works it
		// out, so the estimate on screen is the estimate that will be met.
		// Without a measured build the page cannot know whether the worker will
		// decline to fan out, so this is what it will use where it does.
		workers: workersFor({
			iterations: Math.max(1, Math.round(state.raw.simulation?.iterations ?? 1000)),
			cores: navigator.hardwareConcurrency || 1,
		}),
		// And the reader's own number, where they have given one. Per
		// browser: see ./cores.js.
		cores: chosenCores(),
		// Where the list itself is decided. The tick box says how many there
		// are and this is where they come from -- the picker opens from here
		// and from nowhere else, and a reader who has just been offered "keep
		// only the 12 endpoints" is entitled to ask which twelve.
		onChooseEndpoints: (done) => openEndpoints(
			() => done(ed.endpoints(state.raw), endpointSeriesCount())),
		// What varies besides the parameters and table points, for the list of
		// what will be sampled: the events that draw their occurrences, and the
		// waste packages' ways of failing, which do not.
		implicit: implicitInputs(state.raw),
		onRun: (choice) => startProbabilistic(choice),
	});
}

/**
 * An explicit worker count from the address, or none.
 *
 * `?workers=1` is the serial path, which is what this was before the pool and
 * is the thing to compare against. Anything else is a ceiling the worker
 * applies on top of its own arithmetic -- it will still decline to fan out a
 * model whose build dwarfs its solve.
 */
function workerLimit() {
	const asked = new URLSearchParams(location.search).get('workers');
	if (asked == null) return null;
	const n = Math.round(Number(asked));
	return Number.isFinite(n) && n >= 1 ? n : null;
}

/** Posts the run to the worker and puts the interface into its running state. */
function startProbabilistic(choice) {
	const w = ensureWorker();
	state.runId = (state.runId ?? 0) + 1;
	// Which model this is a run of, taken now rather than when it lands: an
	// edit made while a thousand realisations are integrating must not be
	// able to pass itself off as the model they were drawn from. The same
	// reason `runSimulation` takes `runRev` at the start.
	state.probRev = state.rev;
	// Remembered with the model, so a comparison can be repeated tomorrow:
	// which inputs were varied is as much a part of what was run as the seed.
	// Not an edit that invalidates anything -- it changes no number in the
	// model itself -- so it goes in as a layout-only change.
	const sim = state.raw.simulation ?? (state.raw.simulation = {});
	const partial = choice.varied ?? null;
	let moved = false;
	if (JSON.stringify(sim.partial ?? null) !== JSON.stringify(partial)) {
		if (partial) sim.partial = partial; else delete sim.partial;
		moved = true;
	}
	// The correlations too: which inputs move together is as much a part of
	// what was run as which of them varied.
	const corr = choice.correlations ?? [];
	if (JSON.stringify(sim.correlations ?? []) !== JSON.stringify(corr)) {
		if (corr.length) sim.correlations = corr; else delete sim.correlations;
		moved = true;
	}
	if (moved) modelChanged({ layoutOnly: true });
	chooseCores(choice.cores ?? null);
	state.probRunning = true;
	setRunning(true);
	setLoadingStage('building');
	clearError();
	// The tree's marks are about the sample being replaced, and go while the
	// new one is drawn.
	renderRail();
	w.postMessage({
		type: 'probabilistic',
		id: state.runId,
		project: structuredClone(state.raw),
		iterations: choice.iterations,
		seed: choice.seed,
		latin: choice.latin,
		blocks: choice.blocks,
		// Which of the sampled inputs vary. Null is all of them.
		varied: choice.varied,
		// `?workers=1` runs it the old way, on one thread. For measuring what
		// the pool is worth, for a machine that is busy with something else,
		// and for the case where a browser will nest workers but should not.
		// Left to the worker otherwise, which knows what the last build cost.
		workers: workerLimit(),
		// The reader's number from the dialog, which the worker uses as it
		// stands; null leaves it to the worker.
		cores: chosenCores(),
		// Said in the dialog: hold a sample past what every machine can give
		// a tab. See MOST_BYTES_ASKED in ../sim/probabilistic.js.
		large: choice.large === true,
	});
}

/**
 * The worker would not reuse the states after all, so they are solved again.
 *
 * Its test is structural -- the state layout of what the model actually built
 * into -- where the page's is over the model text, and the two can disagree:
 * an edit that changes no equation the integration reads can still change how
 * many states there are, through an index list a sub-system turns on. The
 * worker's answer is the one that decides, and this is what it costs when it
 * says no: one build, thrown away, and then the run that was going to happen
 * anyway.
 */
function acceptReuseRefused(m) {
	if (m.ok || m.id !== state.runId) return;
	state.reusing = false;
	// The key is wrong, whatever it was: it claimed these two models integrate
	// alike and the builder disagreed. Dropped rather than kept, so the next
	// edit does not ask the same question and get the same wrong answer.
	state.integrationKey = null;
	ensureWorker().postMessage({
		type: 'run', id: state.runId, rev: state.rev, project: state.project.toJSON(),
		cores: splitShare(), workers: workerLimit(),
	});
}

/** The bands are in. */
function acceptProbabilistic(payload, runId) {
	state.probRunning = false;
	// Under its own run id, the way results carry theirs: the matrix stays in
	// the worker and is fetched later, by which time another run may well have
	// taken the current id. And under the revision it was a run of, which is
	// what `currentProb` asks before letting any of this on screen.
	state.prob = { ...payload, runId, rev: state.probRev ?? state.rev };
	// The answer is about other realisations now, so the last one's histograms
	// are not an answer to anything.
	state.hist = null;
	state.points = null;
	state.tableCols = null;
	state.tableRaw = null;
	state.tableRawCols = null;
	// Which picture this run opens on is decided in `renderResults`, once there
	// is a selection to decide it about -- pressing Probabilistic… on a model
	// that has never been run gets its selection from the ordinary run that
	// follows this one, and there is nothing to look at yet.
	state.probModeFor = null;
	setRunning(false);
	if (payload.stats?.correlationProblems?.length) {
		flash(`Correlations ignored: ${payload.stats.correlationProblems[0]}`, 'warn');
	} else if (payload.stats?.correlationAdjusted > 0.005) {
		flash(`The correlations asked for are not all achievable together; the nearest set `
			+ `that is was used (largest change ${payload.stats.correlationAdjusted.toFixed(2)}).`, 'warn');
	}
	const { stats } = payload;
	flash(`${payload.iterations.toLocaleString()} realisations in `
		+ `${(stats.ms / 1000).toFixed(1)} s`
		+ (stats.workers > 1 ? ` over ${stats.workers} cores` : ' on one core')
		+ `${stats.failed ? `, ${stats.failed} of them failed` : ''}.`, 'info');
	renderResults();
	// The panel too: *What drove it* appears only once there is a sample to
	// read, and the panel is not otherwise rebuilt by a run. And the tree,
	// which marks what the sample holds and has a filter for it.
	renderSidebar();
	renderRail();
	renderStaleness();
	// A band is drawn *over* the series the chart knows about, and the chart
	// knows about them from an ordinary run: the labels, the units, the index
	// tuples and the time grid all come from there. Pressing Probabilistic… on
	// a model that has never been run therefore left a thousand realisations
	// in the worker and an empty chart saying nothing had run.
	//
	// So it is run now, once. Against the thousand just integrated it costs
	// nothing, and everything downstream -- the picker, the table, the CSV,
	// *What drove it* -- works exactly as it does when the two are done in the
	// other order.
	//
	// And when the run on screen is of an *older* model, for the same reason:
	// a sample belongs under its own line or under none, so a band drawn over
	// a stale run is not drawn at all. That is right, but it leaves a reader
	// who has just imported a file with a finished sample and nothing to show
	// for it.
	if (!state.running && (!state.results || state.results.rev !== state.rev)) {
		flash('Integrating the model once so the realisations have something to '
			+ 'be drawn over…', 'info');
		runSimulation({ manual: true });
	}
}

/**
 * Throw the sample away, at the reader's word.
 *
 * A sample is the one expensive thing this tool holds: a thousand realisations
 * of every kept series, in the page and again in the worker that integrated
 * them. It falls out of date on its own with the next edit, but until then
 * there is no way to say "I am done with that" -- and a reader who has seen
 * what they came for and wants the memory back, or wants the chart to stop
 * being about a sample, should not have to touch the model to get it.
 *
 * Everything derived from it goes with it, including the pictures that have no
 * meaning without one: a histogram of nothing is not a picture of anything.
 */
function discardProb() {
	if (!state.prob) return;
	state.prob = null;
	state.hist = null;
	state.points = null;
	state.tableCols = null;
	state.tableRaw = null;
	state.tableRawCols = null;
	state.probModeFor = null;
	state.sensFor = null;
	state.tornado = null;
	// The chart has two pictures that exist only for a sample.
	if (state.chartMode !== 'time') state.chartMode = 'time';
	// And the lines, back to this model's own default. Only the deterministic
	// run is drawable now in any case; what this decides is what the *next*
	// sample opens as, and that should be the default rather than whatever
	// was up when the reader finished with the last one.
	state.chartLines = { median: true, mean: !!state.raw?.simulation?.show_mean, single: false };
	// The realisations themselves, which are held in the worker and are the
	// megabyte this is really about.
	worker?.postMessage({ type: 'prob-forget' });
	flash('The realisations were discarded.', 'info');
	renderResults();
	renderSidebar();
	// The tree's marks and its Probabilistic chip were about the sample.
	renderRail();
	renderStaleness();
}

/** New bands for the run on screen: other percentiles, or other categories. */
function acceptProbBands(m) {
	const prob = currentProb();
	if (!prob || m.gone || m.id !== prob.runId) return;
	prob.quantiles = m.quantiles;
	prob.bands = m.bands;
	if (m.screen !== undefined) prob.screen = m.screen;
	renderResults();
}

/** The realisations sorted, and everything redrawn over the ones kept. */
function acceptCategories(m) {
	const prob = currentProb();
	if (!prob || m.id !== prob.runId) return;
	if (m.gone) {
		flash('The realisations are no longer held — run the model probabilistically again.', 'warn');
		return;
	}
	prob.screen = m.screen;
	prob.quantiles = m.quantiles;
	prob.bands = m.bands;
	catModal?.update({ screen: m.screen, iterations: prob.iterations });
	renderResults();
	// What drove it, if it is up, is now about a different set of realisations:
	// the same question again, as the dialog has it -- asked from here with no
	// time, it came back for the last time whatever its *At* said.
	if (sensModal && state.sensFor) sensModal.reask();
}

let catModal = null;

/**
 * The categories editor. The categories are the model's -- saved with it, as
 * the seed is -- and applied to whichever run stands, so the counts are live.
 */
function openCategories() {
	const prob = currentProb();
	const outputs = prob
		? prob.outputs.map((o) => o.label)
		: (state.results?.outputs ?? []).map((o) => o.label);
	if (catModal) { catModal.close(); catModal = null; }
	catModal = openCategoriesDialog({
		categories: categoriesOf(state.raw),
		outputs,
		t: prob?.t ?? state.results?.t ?? [],
		timeUnit: state.raw.simulation?.time_unit ?? 'year',
		screen: prob?.screen ?? null,
		iterations: prob?.iterations ?? 0,
		onChange: (cats) => {
			const sim = state.raw.simulation ?? (state.raw.simulation = {});
			// Saved as written, `include` included; NaN values cannot survive
			// JSON, so an unfinished row is stored without one and read back
			// as a category with a problem, which is what it is.
			sim.categories = cats.map((c) => {
				const out = { label: c.label, output: c.output, stat: c.stat, op: c.op, include: c.include !== false };
				if (c.stat === 'at') out.at = c.at;
				if (Number.isFinite(c.value)) out.value = c.value;
				if (c.op === 'between' && Number.isFinite(c.value2)) out.value2 = c.value2;
				return out;
			});
			modelChanged({ layoutOnly: true });
			const p = currentProb();
			if (p) {
				ensureWorker().postMessage({ type: 'prob-categories', id: p.runId, categories: sim.categories });
			}
		},
		onClose: () => { catModal = null; },
	});
}

/** The percentiles the bands are drawn at. */
function openBands() {
	const prob = currentProb();
	openBandsDialog({
		percentiles: prob?.quantiles ?? state.raw.simulation?.percentiles ?? [0.05, 0.25, 0.5, 0.75, 0.95],
		showMean: !!state.raw.simulation?.show_mean,
		onApply: ({ percentiles, showMean }) => {
			const sim = state.raw.simulation ?? (state.raw.simulation = {});
			sim.percentiles = percentiles;
			if (showMean) sim.show_mean = true; else delete sim.show_mean;
			// The setting is the model's default for one of the chart's three
			// lines, so saying it here turns that line on rather than leaving
			// the reader to find the box.
			state.chartLines = { ...state.chartLines, mean: showMean };
			modelChanged({ layoutOnly: true });
			const p = currentProb();
			if (p) ensureWorker().postMessage({ type: 'prob-bands', id: p.runId, percentiles });
			else renderResults();
		},
	});
}

let distModal = null;

/**
 * One output as a distribution: at a time, where it peaks on average (`at:
 * 'peak'`), or at each realisation's own peak (`at: 'max'`).
 */
function openDistribution(at = null, index = null) {
	const prob = currentProb();
	if (!prob) { flash('Run the model probabilistically first.', 'warn'); return; }
	const target = sensitivityTarget(prob, state.results, state.selected, index, true);
	if (!target) { flash('The probabilistic run kept no series to summarise.', 'warn'); return; }
	state.distFor = { index: target.index };
	ensureWorker().postMessage({
		type: 'prob-summary', id: prob.runId, index: target.index, at: at ?? undefined,
	});
}

function acceptSummary(m) {
	const prob = currentProb();
	if (!prob || m.id !== prob.runId) return;
	if (m.gone) {
		distModal?.close();
		flash('The realisations are no longer held — run the model probabilistically again.', 'warn');
		return;
	}
	const answer = {
		output: prob.outputs[m.index]?.label ?? '',
		unit: prob.outputs[m.index]?.unit ?? '',
		index: m.index, t: m.t, at: m.at, peaks: m.peaks ?? null,
		summary: m.summary, column: m.column, of: m.of,
		spec: m.spec ?? null, screened: !!m.screened,
	};
	if (distModal) { distModal.update(answer); return; }
	distModal = openDistributionDialog({
		...answer,
		outputs: prob.outputs.map((o) => o.label),
		timeUnit: state.raw.simulation?.time_unit ?? 'year',
		onAsk: ({ index, at }) => openDistribution(at, index),
		onClose: () => { distModal = null; },
	});
}

/**
 * One realisation again, in full. The settings are the run's own -- seed,
 * count, sampling, what varied -- so the draws come out the same.
 */
function openReplay(suggested = 1) {
	const prob = currentProb();
	if (!prob) { flash('Run the model probabilistically first.', 'warn'); return; }
	if (state.running) { flash('A run is already going. Stop it first.', 'warn'); return; }
	openReplayDialog({
		iterations: prob.iterations, seed: prob.stats.seed, suggested,
		onRun: (index) => replayRealisation({
			seed: prob.stats.seed, iterations: prob.iterations, latin: prob.stats.latin !== false,
			varied: state.raw.simulation?.partial ?? null,
		}, index),
	});
}

function replayRealisation(settings, index) {
	const w = ensureWorker();
	state.runId += 1;
	state.runRev = state.rev;
	state.runSolver = state.raw.simulation?.solver ?? DEFAULT_SOLVER;
	// A replay is not the model at its values, so nothing later may reuse
	// its states as if it were.
	state.runKey = null;
	state.reusing = false;
	setRunning(true);
	setLoadingStage('building');
	clearError();
	w.postMessage({
		type: 'replay', id: state.runId, project: structuredClone(state.raw),
		index, ...settings,
	});
}

let torModal = null;

/** A tornado: price it, then run it through the pool. */
function openTornado() {
	if (state.running) { flash('A run is already going. Stop it first.', 'warn'); return; }
	let plan;
	try {
		plan = samplingPlan(new Project(structuredClone(state.raw)));
	} catch (e) {
		showError({ name: e.name ?? 'Error', message: e.message, blockName: e.blockName ?? null });
		return;
	}
	if (!plan.length) { flash('No parameter in this model has a distribution to swing.', 'warn'); return; }
	openTornadoSetup({
		plan,
		lastSolveMs: state.lastSolveMs || null,
		workers: workersFor({ iterations: 2 * plan.length + 1, cores: navigator.hardwareConcurrency || 1 }),
		cores: chosenCores(),
		endpoints: ed.endpoints(state.raw),
		simulation: state.raw.simulation ?? {},
		onRun: (choice) => {
			chooseCores(choice.cores ?? null);
			const sim = state.raw.simulation ?? (state.raw.simulation = {});
			if (sim.tornado_low !== choice.low || sim.tornado_high !== choice.high) {
				sim.tornado_low = choice.low;
				sim.tornado_high = choice.high;
				modelChanged({ layoutOnly: true });
			}
			const w = ensureWorker();
			state.runId += 1;
			state.tornadoRev = state.rev;
			state.tornadoRunning = true;
			setRunning(true);
			setLoadingStage('building');
			clearError();
			// The output the table opens on: the chart's first line, as What
			// drove it does.
			const first = state.selected.length ? state.results?.outputs[state.selected[0]]?.label : null;
			w.postMessage({
				type: 'tornado', id: state.runId, project: structuredClone(state.raw),
				tornado: { low: choice.low, high: choice.high },
				blocks: choice.blocks,
				varied: state.raw.simulation?.partial ?? null,
				index: 0, stat: 'max', at: 0, wantLabel: first,
				workers: workerLimit(),
				cores: chosenCores(),
			});
		},
	});
}

function acceptTornado(m) {
	state.tornadoRunning = false;
	setRunning(false);
	if (m.id !== state.runId) return;
	// Opened on the line the chart shows, when the tornado kept it.
	const first = state.selected.length ? state.results?.outputs[state.selected[0]]?.label : null;
	const k = first ? m.outputs.findIndex((o) => o.label === first) : -1;
	state.tornado = { ...m, runId: m.id, rev: state.tornadoRev ?? state.rev };
	flash(`Tornado: ${m.points.toLocaleString()} runs in ${(m.stats.ms / 1000).toFixed(1)} s`
		+ (m.stats.workers > 1 ? ` over ${m.stats.workers} cores` : ' on one core') + '.', 'info');
	if (k >= 0 && k !== m.table.index) {
		ensureWorker().postMessage({ type: 'tornado-table', id: m.id, index: k, stat: m.table.stat, at: m.table.at });
	}
	const swing = { low: m.stats.tornado?.low ?? 0.05, high: m.stats.tornado?.high ?? 0.95 };
	if (torModal) torModal.close();
	torModal = openTornadoResult({
		outputs: m.outputs.map((o) => o.label), t: m.t, table: m.table, points: m.points,
		timeUnit: state.raw.simulation?.time_unit ?? 'year', swing,
		onAsk: ({ index, stat, at }) => ensureWorker().postMessage({
			type: 'tornado-table', id: m.id, index, stat, at,
		}),
		onReplay: (point) => replayRealisation({
			tornado: swing, varied: state.raw.simulation?.partial ?? null,
			seed: 0, iterations: m.points,
		}, point),
		onClose: () => { torModal = null; },
	});
}

function acceptTornadoTable(m) {
	if (!state.tornado || m.id !== state.tornado.runId) return;
	if (m.gone) { torModal?.close(); flash('The tornado runs are no longer held.', 'warn'); return; }
	state.tornado.table = m.table;
	torModal?.update({ table: m.table });
}

let gsaModal = null;

/**
 * A global sensitivity design: choose the method, price it, run it through
 * the pool. See ../domain/gsa.js for the methods and ./gsadialog.js for the
 * two dialogs.
 */
function openGsa() {
	if (state.running) { flash('A run is already going. Stop it first.', 'warn'); return; }
	let plan;
	try {
		plan = samplingPlan(new Project(structuredClone(state.raw)));
	} catch (e) {
		showError({ name: e.name ?? 'Error', message: e.message, blockName: e.blockName ?? null });
		return;
	}
	if (!plan.length) { flash('No parameter in this model has a distribution to vary.', 'warn'); return; }
	// What the design will vary, counted the way the worker will count it: a
	// correlation group is one input, and a partial run's held inputs are not
	// inputs at all. See `gsaDesignFor` in ../sim/probabilistic.js.
	const partial = state.raw.simulation?.partial;
	const varied = Array.isArray(partial) ? new Set(partial) : null;
	const keys = new Map();
	const factorOf = new Map();
	plan.forEach((e) => {
		const name = slotName(e);
		if (varied && !varied.has(name)) return;
		const group = groupOf(e);
		const key = group ?? name;
		keys.set(key, group != null);
		factorOf.set(name, key);
	});
	const inputs = keys.size;
	const grouped = [...keys.values()].filter(Boolean).length;
	const correlated = (state.raw.simulation?.correlations ?? []).filter((c) => {
		const a = factorOf.get(String(c?.a));
		const b = factorOf.get(String(c?.b));
		return c?.group != null || (a != null && b != null && a !== b);
	}).length;
	openGsaSetup({
		inputs, grouped, correlated,
		lastSolveMs: state.lastSolveMs || null,
		workers: workersFor({ iterations: 1000, cores: navigator.hardwareConcurrency || 1 }),
		cores: chosenCores(),
		endpoints: ed.endpoints(state.raw),
		simulation: state.raw.simulation ?? {},
		onRun: (choice) => {
			chooseCores(choice.cores ?? null);
			// Remembered with the model, as the tornado's percentiles are: which
			// method, with what, and from which seed is what makes the answer
			// one that can be had again. It changes no number in the model.
			const sim = state.raw.simulation ?? (state.raw.simulation = {});
			const record = { method: choice.method, options: choice.options, seed: choice.seed };
			if (JSON.stringify(sim.gsa ?? null) !== JSON.stringify(record)) {
				sim.gsa = record;
				modelChanged({ layoutOnly: true });
			}
			const w = ensureWorker();
			state.runId += 1;
			state.gsaRev = state.rev;
			state.gsaRunning = true;
			setRunning(true);
			setLoadingStage('building');
			clearError();
			// The output the table opens on: the chart's first line, as the
			// tornado does.
			const first = state.selected.length ? state.results?.outputs[state.selected[0]]?.label : null;
			w.postMessage({
				type: 'gsa', id: state.runId, project: structuredClone(state.raw),
				gsa: { method: choice.method, options: choice.options },
				seed: choice.seed,
				blocks: choice.blocks,
				varied: state.raw.simulation?.partial ?? null,
				index: 0, stat: 'max', at: 0, wantLabel: first,
				workers: workerLimit(),
				cores: chosenCores(),
			});
		},
	});
}

function acceptGsa(m) {
	state.gsaRunning = false;
	setRunning(false);
	if (m.id !== state.runId) return;
	const first = state.selected.length ? state.results?.outputs[state.selected[0]]?.label : null;
	const k = first ? m.outputs.findIndex((o) => o.label === first) : -1;
	state.gsa = { ...m, runId: m.id, rev: state.gsaRev ?? state.rev };
	const failed = m.stats.failed ? `, ${m.stats.failed} of them failed` : '';
	flash(`Sensitivity: ${m.points.toLocaleString()} runs in ${(m.stats.ms / 1000).toFixed(1)} s`
		+ (m.stats.workers > 1 ? ` over ${m.stats.workers} cores` : ' on one core') + `${failed}.`,
	m.stats.failed ? 'warn' : 'info');
	if (k >= 0 && k !== m.answer.index) {
		ensureWorker().postMessage({ type: 'gsa-table', id: m.id, index: k, stat: m.answer.stat, at: m.answer.at });
	}
	showGsa();
}

/**
 * The last design's result, in its window.
 *
 * Opened when the runs come in, and again from Analyse ▾ → Global sensitivity
 * result… after the window has been closed: the worker holds the runs until
 * the next design or another model, so the table for any output and reading
 * is still one question away rather than another thousand runs. On whatever
 * output and reading it was last left at.
 */
function showGsa() {
	const g = state.gsa;
	if (!g) return;
	if (gsaModal) gsaModal.close();
	gsaModal = openGsaResult({
		outputs: g.outputs.map((o) => o.label), t: g.t, answer: g.answer, points: g.points, stats: g.stats,
		timeUnit: state.raw.simulation?.time_unit ?? 'year',
		// Said rather than refused: the runs are still an answer about the
		// model they were made of, and the reader may want exactly that.
		stale: g.rev !== state.rev,
		onAsk: ({ index, stat, at }) => ensureWorker().postMessage({
			type: 'gsa-table', id: g.runId, index, stat, at,
		}),
		onClose: () => { gsaModal = null; },
	});
}

function acceptGsaTable(m) {
	if (!state.gsa || m.id !== state.gsa.runId) return;
	if (m.gone) { gsaModal?.close(); flash('The sensitivity runs are no longer held.', 'warn'); return; }
	state.gsa.answer = m.answer;
	gsaModal?.update({ answer: m.answer });
}

/**
 * Asks the worker which inputs drove the series being looked at.
 *
 * The series is the chart's first selected line: a sensitivity is about one
 * output, and the one in front of you is the one you mean. Asked of the worker
 * rather than worked out here because the sample lives there -- a thousand
 * realisations of every kept series, which is the thing that was deliberately
 * not sent to the page.
 */
function openSensitivity(at = null, index = null, translate = 'none', family = 'regression', inputs = null) {
	const prob = currentProb();
	if (!prob) { flash('Run the model probabilistically first.', 'warn'); return; }
	const target = sensitivityTarget(prob, state.results, state.selected, index);
	if (!target) {
		flash('The probabilistic run kept no series to ask about.', 'warn');
		return;
	}
	const { index: which, fellBack } = target;
	if (fellBack) {
		flash(`That line was not part of the probabilistic run — showing `
			+ `${prob.outputs[which].label} instead. Pick another under “Of”.`, 'warn');
	}
	state.sensFor = { index: which, label: prob.outputs[which]?.label ?? '' };
	ensureWorker().postMessage({
		type: 'sensitivity',
		// The *probabilistic* run's id, not the current one. The worker keeps
		// one sample, under the id of the run that drew it, and answers only
		// questions that name it -- so asked under `state.runId`, this went
		// unanswered the moment anything else had been run since, and the
		// worker's refusal was a silent `return`. The button did nothing at
		// all: no dialog, no notice, nothing in the strip. `askProbMatrices`
		// below has always got this right; this is the same rule.
		id: prob.runId,
		index: which,
		// A number, the string `peak` -- "wherever this output is largest on
		// average" -- or `max`, each realisation's own peak. Only the worker
		// can work out the second and third, because only the worker has the
		// matrix.
		at: at ?? undefined,
		most: 20,
		translate,
		// Which measures beside the correlations: the regression family, or
		// the ones that read the whole distribution (EASI, δ, mutual
		// information, RSA). The second is a bootstrap per input and is
		// worked out only when asked for.
		family,
		// Which sampled inputs the analysis is over, as sample columns; all of
		// them when absent.
		inputs: Array.isArray(inputs) ? inputs : undefined,
	});
}

/**
 * The coefficients are in.
 *
 * Into the dialog that is already up where there is one. Both of its pickers --
 * which series, and at which time -- ask the worker again, and this used to
 * answer by opening another dialog on top: change the time three times and
 * there were four of them stacked, each holding an older table than the one
 * over it.
 */
let sensModal = null;

function acceptSensitivity(m) {
	// The worker no longer holds that sample -- it keeps one, and a later
	// probabilistic run has replaced it. Said rather than dropped: the reader
	// pressed a button and is owed an answer, even when the answer is no.
	if (m.gone) {
		state.sensFor = null;
		sensModal?.close();
		flash('The realisations that answer this are no longer held — '
			+ 'run the model probabilistically again.', 'warn');
		return;
	}
	const prob = currentProb();
	const answer = {
		output: prob?.outputs[m.index]?.label ?? state.sensFor?.label ?? '',
		index: m.index,
		t: m.t,
		at: m.at,
		peaks: m.peaks ?? null,
		rows: m.rows,
		curves: m.curves,
		measures: m.measures ?? null,
		distribution: m.distribution ?? null,
		kept: m.kept ?? null,
		sampled: m.sampled ?? [],
		using: m.using ?? null,
		iterations: prob?.iterations ?? 0,
	};
	if (sensModal) { sensModal.update(answer); return; }
	sensModal = openSensitivityDialog({
		...answer,
		// Only what the run kept: those are the series it can answer for, and
		// the picker should not offer one it would refuse. Not the varied
		// parameters, which are what it answers *with*.
		outputs: (prob?.outputs ?? []).filter((o) => !o.varied).map((o) => o.label),
		timeUnit: state.raw.simulation?.time_unit ?? 'year',
		onAsk: ({ index, at, translate, family, inputs }) => openSensitivity(at, index, translate, family, inputs),
		onClose: () => { sensModal = null; },
	});
}

/**
 * dy/dp: pick the parameters, then integrate the model and its sensitivities.
 *
 * Needs no distributions -- it is a derivative at the values the model holds --
 * so it is offered whatever the model carries, unlike the probabilistic run.
 */
function openLocalSensitivity() {
	if (state.running) { flash('A run is already going. Stop it first.', 'warn'); return; }
	let slots;
	let states;
	let exact = true;
	try {
		const sys = buildSystem(new Project(structuredClone(state.raw)));
		slots = parameterSlots(sys).map((s) => ({ label: slotLabel(s), value: s.value }));
		states = sys.layout.nstate;
		// Whether `df/dp` will be generated or differenced, which is what the
		// cost sentence in the dialog turns on. Read off the layout rather than
		// by asking for the tangent: generating it is the expensive half, and
		// the three block types that refuse it are a structural fact.
		exact = !(sys.layout.farfields ?? []).length
			&& !(sys.layout.wastes ?? []).length
			&& !(sys.layout.events ?? []).length;
	} catch (e) {
		showError({ name: e.name ?? 'Error', message: e.message, blockName: e.blockName ?? null });
		flash(`Sensitivity needs a model that builds. ${e.message}`, 'warn');
		return;
	}
	if (!slots.length) { flash('This model has no parameters to differentiate against.', 'warn'); return; }
	openLocalSensitivityPicker({
		slots,
		states,
		exact,
		onRun: (parameters) => {
			const w = ensureWorker();
			state.runId = (state.runId ?? 0) + 1;
			setRunning(true);
			setLoadingStage('building');
			clearError();
			w.postMessage({
				type: 'local-sensitivity',
				id: state.runId,
				project: structuredClone(state.raw),
				parameters,
			});
		},
	});
}

/** The sensitivities are in. */
function acceptLocalSensitivity(m) {
	setRunning(false);
	openLocalSensitivityResult({
		t: m.t,
		chosen: m.chosen,
		states: m.states,
		timeUnit: state.raw.simulation?.time_unit ?? 'year',
		stats: m.stats,
	});
}

/**
 * The realisation matrices for a few series, from the worker that holds them.
 *
 * One request outstanding at a time, which is all an export needs and is why
 * this is a variable rather than a table. Matched against the probabilistic
 * run's own id: `state.runId` has moved on if anything has been run since, and
 * a reply for a run whose result has been replaced is not an answer to this.
 */
let probMatrixWait = null;

function acceptProbMatrix(m) {
	const wait = probMatrixWait;
	if (!wait || m.id !== wait.id) return;
	probMatrixWait = null;
	wait.resolve(m.gone ? null : m);
}

function askProbMatrices(indices, want = 'all', { compact = false } = {}) {
	const id = currentProb()?.runId;
	if (id == null) return Promise.resolve(null);
	return new Promise((resolve) => {
		probMatrixWait = { id, resolve };
		// `compact`: a series that cannot change over the run comes back as one
		// row, the value in each realisation, rather than that row at every
		// time -- which is what a file wants of it (../io/resultfile.js).
		ensureWorker().postMessage({ type: 'prob-matrix', id, indices, want, compact });
	});
}

/**
 * How long Stop waits for the worker to say it has closed its own workers.
 *
 * Long enough for a message to cross twice on a busy machine, short enough
 * that nobody sees it. If it passes, the worker is terminated anyway -- which
 * is the deterministic case, where nothing was ever going to answer.
 */
const STOP_GRACE = 250;

function cancelSimulation() {
	if (!state.running) return;
	// Stop means stop: an edit made while this run was going does not get to
	// start another one the moment this one dies. Both halves of that -- the
	// run already queued behind this one, and the timer of an edit whose 350
	// milliseconds have not elapsed yet, which would otherwise queue one an
	// instant after the Stop.
	runWanted = false;
	clearTimeout(autoRunTimer);
	autoRunTimer = null;

	// Terminated, not asked. A message to a worker is only delivered between
	// turns of its event loop, and a solve is one long synchronous call -- so
	// `postMessage({type:'cancel'})` sat in the queue until the run it was
	// meant to stop had already finished. The flag the solvers poll
	// (`signal.aborted`, runner.js) could never change while it mattered, and
	// Stop did nothing but stay lit while a core kept burning.
	//
	// Two things the message *can* reach, and both get a moment to hear it.
	// The Pyodide download is awaited and therefore yields. And a probabilistic
	// run shared over the cores leaves this worker idle -- it is waiting on the
	// workers it started, not solving -- so `cancel` is delivered, and it is
	// the only chance anything has to kill those children: terminating their
	// parent leaves them holding a core each and a matrix each with nothing
	// able to talk to them.
	//
	// So: ask, wait a moment for the worker to say the children are gone, and
	// terminate whether it answered or not. A deterministic run never answers,
	// because it is one long synchronous call -- which is why terminating
	// exists at all -- and the wait is short enough to be invisible.
	// The scenarios running beside it go the same way, and at once: each is
	// one long synchronous solve in a worker of its own, which nothing but
	// terminating reaches.
	stopScenarios();
	if (worker) {
		const going = worker;
		worker = null;
		detachResults();
		let done = false;
		const kill = () => {
			if (done) return;
			done = true;
			going.terminate();
		};
		going.addEventListener('message', (ev) => { if (ev.data?.type === 'cancelled') kill(); });
		going.postMessage({ type: 'cancel' });
		setTimeout(kill, STOP_GRACE);
	}
	// Stop is a statement about auto-run as much as about this run. Left on, the
	// next edit -- or the one already typed, 350 ms ago -- starts the very run
	// that was just stopped, and the only way out is to keep pressing Stop
	// faster than the model is edited. So the switch goes off, and visibly:
	// this is a control the person set, and changing it behind their back is
	// worse than the run they were trying to escape.
	//
	// Not `autoRunHeld`, which is the other thing: a slow solve holds auto-run
	// back without touching the switch, because nobody asked for that one.
	const wasAuto = state.autoRun;
	if (wasAuto) {
		state.autoRun = false;
		const box = $('#autorun');
		if (box) box.checked = false;
	}

	// The run this was stopping will never report, so nothing else will take
	// the interface out of its running state.
	setRunning(false);
	// A result already on screen is the *previous* model's; `renderStaleness`
	// is what says so, and it is called from `setRunning`.
	flash(wasAuto ? 'Stopped, and auto-run switched off.' : 'Stopped.', 'info');
}

/**
 * @param {boolean} on
 * @param {{keepStatus?: boolean}} [opts]  `keepStatus` for a run that adds to
 *   the results on screen rather than replacing them -- a scenario ticked
 *   beside results that are current -- whose status line is still true
 */
function setRunning(on, { keepStatus = false } = {}) {
	state.running = on;
	if (!on) state.primaryBusy = false;
	// A pool is one run's: the next says what it is on for itself.
	state.pool = null;
	$('#run').disabled = on;
	$('#cancel').hidden = !on;
	// The progress slot in the footer keeps its space and only appears, so the
	// status line beside it never shifts when a run starts.
	$('#run-progress').classList.toggle('is-on', on);
	if (on) {
		// The last run's numbers go the moment another starts: left up, the
		// steps and the solve time beside a bar that is moving read as this
		// run's. What replaces them is the clock -- when this one started and
		// how long it has been going.
		if (!keepStatus) {
			clearStatus();
			statusOwed = true;
		}
		startRunClock();
		setProgress(0);
		return;
	}
	stopRunClock();
	// A run that brought no results of its own -- a sample, a tornado, a Stop
	// -- leaves the line blank; the results on screen are still the ones it
	// described, so it is put back. Not when the model has moved since: those
	// results are stale, and the line would describe a model no longer here.
	if (statusOwed) {
		statusOwed = false;
		if (state.results && state.results.rev === state.rev && !state.results.detached) setStatus(state.results);
	}
	// Here rather than in `acceptResults`, so that a run which failed or was
	// stopped still lets the edits made during it have their turn. Only if
	// they left the model dirty: what the run that just finished computed may
	// already be this model's.
	if (!runWanted) return;
	runWanted = false;
	const manual = runWantedManual;
	runWantedManual = false;
	if (!state.dirty) return;
	if (state.autoRun) scheduleAutoRun();
	else if (manual) runSimulation({ manual: true });
}

/**
 * @param {number} fraction 0..1, of the span in model time
 * @param {number} [at] the model clock, when the run has one to report
 *
 * **Not** that fraction, where there is anything better. A fraction of the
 * span is a poor account of how far a stiff run has got: the first per cent
 * of the time can be a tenth of the work, and a silo model of 8,427 states
 * sits at 0% for the first ten seconds by that measure. What the run is
 * actually producing is output points, and on a grid that is dense where the
 * model is interesting -- which is every log-spaced grid, and every series a
 * real file carries -- the first few tick over early and the rest follow
 * steadily. So the bar counts points reached, and the clock goes beside it,
 * since a number that moves is the difference between waiting and reloading.
 */
function setProgress(fraction, at = null) {
	const bar = $('#progress');
	if (bar.hasAttribute('data-loading')) bar.removeAttribute('data-loading');
	const grid = state.grid;
	// Monotone, and walked rather than searched: the reports arrive in order.
	if (grid && grid.length > 2 && at != null && Number.isFinite(at)) {
		while (state.gridAt < grid.length && grid[state.gridAt] <= at) state.gridAt++;
	}
	state.primaryFraction = grid && grid.length > 2 && at != null && Number.isFinite(at)
		? state.gridAt / grid.length
		: Math.max(0, Math.min(1, fraction));
	state.primaryAt = at;
	paintProgress();
}

/**
 * The bar, and the words beside it.
 *
 * One run: how far it has got, and its clock. With scenarios running beside
 * it, the share of the whole that is done -- a run that is in counts in full --
 * and how many are in, since one clock would be one scenario's.
 */
function paintProgress() {
	const bar = $('#progress');
	const text = $('#progress-pct');
	if (!bar || !text) return;
	const batch = [...state.scenarioRuns.values()].filter((e) => e.runId === state.runId
		|| e.running || e.queued);
	let f = state.primaryFraction ?? 0;
	let at = state.primaryAt ?? null;
	let also = '';
	if (batch.length) {
		// The selected scenario's building phase keeps the bar indeterminate
		// while it lasts, as it does alone; once it is in, the bar is the
		// batch's.
		if (!state.primaryBusy && bar.hasAttribute('data-loading')) bar.removeAttribute('data-loading');
		if (bar.hasAttribute('data-loading')) return;
		const shares = [state.primaryBusy ? f : 1,
			...batch.map((e) => (e.running || e.queued ? (e.fraction ?? 0) : 1))];
		f = shares.reduce((a, b) => a + b, 0) / shares.length;
		const done = (state.primaryBusy ? 0 : 1) + batch.filter((e) => !e.running && !e.queued).length;
		also = ` \u00b7 ${done} of ${shares.length} scenarios`;
		at = null;
	} else if (bar.hasAttribute('data-loading')) {
		bar.removeAttribute('data-loading');
	}
	bar.value = f;
	const unit = state.raw?.simulation?.time_unit ?? '';
	const pool = poolNote(state.pool);
	// A sampled run's count as well: of eight thousand realisations one per
	// cent is eighty, and the count is what the time left is worked out from.
	const e = runClock.eta?.run === state.runId ? runClock.eta : null;
	const count = e && !batch.length
		? ` · ${e.done.toLocaleString('en-US').replace(/,/g, '\u2009')} of ${e.of.toLocaleString('en-US').replace(/,/g, '\u2009')}`
		: '';
	// Padded, and in tabular figures, so the digits do not jog the bar.
	text.textContent = `${String(Math.round(f * 100)).padStart(3, ' ')}%`
		+ (at == null || !Number.isFinite(at) ? '' : ` · ${fmtClock(at)}${unit ? ` ${unit}` : ''}`)
		+ count
		+ also
		+ (pool.text ? ` · ${pool.text}` : '');
	text.title = pool.title;
}

/**
 * How many cores a sampled run is on, from the worker, before it builds.
 *
 * Shown for the length of the run, beside the bar, so a reader who chose a
 * number sees it met -- or, in the tooltip, why it was not.
 */
function acceptPool(m) {
	state.pool = { workers: m.workers, asked: m.asked ?? null, why: m.why ?? null };
	const bar = $('#progress');
	const stage = bar.getAttribute('data-loading');
	if (stage) setLoadingStage(stage);
	else setProgress(bar.value ?? 0);
}

/**
 * The model clock, short enough for the footer.
 *
 * Thousands separated, because the run this exists for spans a hundred
 * thousand years and `102000` is not a number anyone reads at a glance; and
 * without decimals, since a bar that jitters through fractions of a year says
 * less than one that counts them.
 */
function fmtClock(t) {
	const a = Math.abs(t);
	if (a >= 1000) return Math.round(t).toLocaleString('en-US').replace(/,/g, ' ');
	if (a >= 1) return t.toFixed(a >= 100 ? 0 : 1);
	return t.toPrecision(2);
}

/**
 * What a SciPy run is waiting for before it can start.
 *
 * The first one downloads a Python runtime, which takes seconds rather than
 * milliseconds. A progress bar sitting at 0% for that long reads as a hang, so
 * it is replaced by a word about what is actually happening, and the bar goes
 * indeterminate.
 */
const LOADING_STAGE = {
	runtime: 'Downloading Python (first SciPy run only)…',
	packages: 'Downloading NumPy and SciPy…',
	starting: 'Starting the Python interpreter…',
	// Not a download: generating the derivative, the tangent function and the
	// sparsity pattern, which on a model of ten thousand states is seconds
	// before the first step is taken. See the worker.
	building: 'Building the model…',
	// Built, and stepping -- but not yet far enough to have reached the first
	// output point. Its own word, because "building" through the first minute
	// of a solve is the label that made a slow model look like a stuck one.
	solving: 'Solving…',
};

function setLoadingStage(stage, detail) {
	const bar = $('#progress');
	const text = $('#progress-pct');
	if (stage === 'ready' || !stage) {
		bar.removeAttribute('data-loading');
		bar.max = 1;
		setProgress(0);
		return;
	}
	// A <progress> with no value is the indeterminate one.
	bar.removeAttribute('value');
	bar.setAttribute('data-loading', stage);
	const pool = poolNote(state.pool);
	text.textContent = (LOADING_STAGE[stage] ?? String(stage)) + (pool.text ? ` · ${pool.text}` : '');
	text.title = detail || pool.title;
}

/**
 * Called after any edit. Re-renders the views and re-runs, unless the last
 * solve was slow enough that doing so on every keystroke would be annoying.
 */
function modelChanged(opts = {}) {
	// Any edit calls off a pending cut: a move whose source has been changed
	// under it is a move nobody asked for. The paste clears it before it moves
	// anything, so this does not cancel the move it is performing.
	clearPendingCut();
	// A lock is honoured here, before anything else looks at the edit: every
	// edit arrives through this one function, so this is the one place a lock
	// cannot be walked round. What it does is put the block back, not refuse
	// the whole edit -- an edit that touched one locked block and four others
	// should keep the four.
	const held = restoreLocked();
	state.dirty = true;
	ed.pruneLayout(state.raw);
	// A flux unit follows from its donor, that donor's unit and the model's
	// time unit -- any of which this edit may have been. Re-deriving once here
	// covers every path, including the matrix editor and the JSON tab.
	ed.syncDerivedUnits(state.raw);
	// After both of those, so that a step back lands on a model that is
	// already settled rather than on one the next edit would have tidied.
	undoStack.record(state.raw, viewNow(), {
		coalesce: opts.coalesce ?? null,
		layoutOnly: !!opts.layoutOnly,
		// What the editor was pointed at, which is what names an edit that
		// changed a value rather than the shape of anything.
		hint: state.settingsFor ?? state.selection?.name ?? null,
	});
	if (!opts.layoutOnly) {
		state.rev += 1;
		// The last run's failure was about the model as it was. Editing it --
		// including deleting the block the message names, which is the obvious
		// way to answer one -- makes the message about a model that no longer
		// exists, and the strip went on saying "from the last run" over a fault
		// the reader had already fixed, with no way to dismiss it. What *is*
		// still wrong is re-derived by `rescanProblems` on every edit; this one
		// is found again by the next run if it is still there.
		state.runProblem = null;
		// And the build's, which is looked for again straight away.
		recheckBuild();
	}
	republish(opts);
	if (held.length) {
		flash(`${held.join(', ')} ${held.length === 1 ? 'is' : 'are'} locked — `
			+ `${held.length === 1 ? 'that change was' : 'those changes were'} put back. `
			+ 'Unlock it under All settings to edit it.', 'warn');
	}
	rememberLocked();
}

/**
 * Puts back anything a lock is holding, and says which.
 *
 * Compared by what a review was *about* — see `stamp` in ../domain/qa.js — so
 * moving a locked block on the diagram, or commenting on it, is not an edit a
 * lock has anything to say about.
 */
function restoreLocked() {
	if (!state.locked.size) return [];
	const broken = [];
	for (const [name, copy] of state.locked) {
		const found = ed.findBlock(state.raw, name);
		if (!found) {
			// Deleted, which is the most complete way of editing something.
			// Put back where it was, in the collection it came from.
			const list = state.raw[copy.collection] ?? (state.raw[copy.collection] = []);
			list.push(structuredClone(copy.block));
			broken.push(name);
			continue;
		}
		if (qa.stamp(found.block) === copy.stamp) continue;
		// Only the fields a review was about: a move or a comment stands.
		const put = structuredClone(copy.block);
		for (const key of Object.keys(found.block)) {
			if (!(key in put) && qa.stamp({ [key]: found.block[key] }) !== '{}') delete found.block[key];
		}
		Object.assign(found.block, put);
		broken.push(name);
	}
	return broken;
}

/** What the locked blocks are now, for the next edit to be compared against. */
function rememberLocked() {
	state.locked.clear();
	if (!qa.enabled(state.raw)) return;
	for (const name of qa.lockedNames(state.raw)) {
		const found = ed.findBlock(state.raw, name);
		if (!found) continue;
		state.locked.set(name, {
			block: structuredClone(found.block),
			collection: found.collection,
			stamp: qa.stamp(found.block),
		});
	}
}

/**
 * Shows the model as it now stands, everywhere it is shown.
 *
 * The tail of `modelChanged`, shared with undo: putting an older model back is
 * not an edit -- nothing needs pruning, nothing needs re-deriving, and nothing
 * goes into the history -- but everything that looks at a model afterwards has
 * to look again, in the same order and for the same reasons.
 */
function republish(opts = {}) {
	// The settings dialog is an editor over the same model: an edit made
	// anywhere may change what it should be showing. Except an edit the dialog
	// is in the middle of making with a control that must survive it: a colour
	// picker reports every colour it passes over, and rebuilding the dialog
	// under it destroyed the input the picker belonged to, which closed the
	// picker at the first click. Those say `keepModal`, and ask for the
	// refresh themselves once the picker is done.
	if (!opts.keepModal) refreshModal();
	// Re-scanned on every edit rather than only when something is typed into a
	// field: a name change three blocks away can break an equation nobody is
	// looking at, and a broken model has to say so wherever it is broken from.
	// Without the rail: `renderEditorViews` two lines down renders it, and
	// building the tree of every block in the model twice is most of what an
	// edit used to cost.
	rescanProblems({ rail: false });
	updateDirtyBadge();
	// Whether there is anything to write, which every edit changes.
	renderSaveButton();
	// Kept for next time, after the typing stops. Here rather than in
	// `modelChanged` so that undo and redo are kept too: what the draft is
	// for is the model on screen, however it got there.
	draftKeeper.note(state.raw, draftMeta());
	renderEditorViews(opts);
	// The JSON tab is rewritten when it is looked at (`selectTab`), not on
	// every edit: serialising the whole model into a textarea nobody can see
	// -- twelve megabytes of it, pretty-printed, for the largest model here --
	// was the single most expensive thing a keystroke did.
	if (state.tab === 'model') renderModelEditor();
	renderUndoButtons();
	if (opts.layoutOnly) {
		// Moving a node changes nothing about the numbers -- but an edit that
		// did may still be waiting for a run, and that is what the badge is
		// about, so it is asked rather than assumed.
		state.dirty = resultsAreStale();
		updateDirtyBadge();
		return;
	}
	// A model with a broken equation is not handed to the solver, and there is
	// no run coming -- so whatever is on the chart is now out of date and has
	// to stop being shown. `renderResults` reads the same test.
	if (!state.autoRun || opts.soft) { renderStaleness(); return; }
	if (autoRunHeld()) { renderStaleness(); return; }
	scheduleAutoRun();
	renderStaleness();
}

/**
 * Where the editor is looking, to be put back with the model it belongs to.
 *
 * Undoing a deletion that does not select what it brought back leaves the
 * block found again but lost, somewhere in a diagram that may not even be the
 * one on screen -- so the selection and the sub-system being shown travel with
 * each step. They are copied out: `picked` is edited in place elsewhere.
 */
function viewNow() {
	return {
		selection: state.selection ? { ...state.selection } : null,
		picked: [...state.picked],
		system: graph?.currentSystem ?? '',
	};
}

/**
 * Steps the model back or forward through the edits made to it.
 *
 * The whole model is replaced, which is the point: an undo that walked back
 * over one edit could only be as correct as that edit's inverse, and there are
 * a hundred edits. See undo.js.
 */
function timeTravel(back) {
	const step = back ? undoStack.undo() : undoStack.redo();
	if (!step) {
		flash(back ? 'Nothing left to undo.' : 'Nothing to redo.', 'info');
		return;
	}
	// A gesture still in the pointer's hands writes to the model as it moves,
	// and would go on writing to the one that has just been replaced.
	graph?.cancelGesture();
	// And a cut marked against the model being stepped away from means
	// nothing against the one arriving.
	clearPendingCut();
	const had = new Set(ed.allBlocks(state.raw).map(ed.qualifiedName));
	// When the file was made and last saved are facts about the file, not
	// edits: stepping back through the model leaves them as they are.
	state.raw = ed.keepStamps(step.raw, state.raw);
	// Whatever the step brought back is what the step was about, so that is
	// what ends up selected -- the stored selection only says where the editor
	// was pointed before. The two differ exactly where it matters: deleting
	// clears the selection before the deletion is recorded, so the step
	// remembers nothing selected, and an undo that honoured that would put
	// three blocks back and leave them lost in the diagram.
	const reappeared = ed.allBlocks(state.raw)
		.filter((b) => !had.has(ed.qualifiedName(b)));
	// A deleted compartment takes its transfers with it and an undo brings
	// them all back, but what was deleted was the compartment: the lines are
	// not selected alongside it, any more than they were when it went.
	const nodes = reappeared.filter((b) => b.kind !== 'transfer' && b.kind !== 'inflow');
	const brought = nodes.length ? nodes : reappeared;
	if (brought.length) {
		state.picked = brought.map(ed.qualifiedName);
		state.selection = { kind: brought[0].kind, name: state.picked[0] };
	} else {
		state.selection = step.view?.selection ?? null;
		state.picked = step.view?.picked ?? [];
	}
	// Back to the diagram the edit was made on -- or to the one holding what
	// the step brought back, which is the same thing except when the edit was
	// made somewhere else and reached in. Either way, not to a sub-system the
	// step itself removed: the top level is where its blocks now are.
	// Before `republish`, not after: switching canvases clears the diagram's
	// own selection, and the re-render inside republish is what puts the
	// selection back -- in the other order the blocks would come back on the
	// right canvas with nothing highlighted.
	const where = brought.length
		? parentOf(state.picked[0])
		: step.view?.system ?? '';
	graph?.setSystem(where && ed.systems(state.raw).includes(where) ? where : '');
	state.dirty = true;
	if (!step.layoutOnly) state.rev += 1;
	republish({ layoutOnly: step.layoutOnly });
	flash(`${back ? 'Undid' : 'Redid'}: ${step.label}`);
}

/**
 * Whether the keyboard belongs to something being typed into.
 *
 * A checkbox and a button are `<input>` and `<button>` too, and Cmd+Z with one
 * of them focused means undo -- so this asks what the field does with text
 * rather than what tag it is.
 */
function isTyping(node) {
	if (!node) return false;
	if (node.isContentEditable) return true;
	if (node.tagName === 'TEXTAREA') return true;
	if (node.tagName !== 'INPUT') return false;
	return !['checkbox', 'radio', 'button', 'submit', 'color', 'range', 'file']
		.includes(node.type);
}

/** The two buttons, saying what they would take back or put back. */
function renderUndoButtons() {
	const undo = $('#undo');
	const redo = $('#redo');
	if (!undo || !redo) return;
	undo.disabled = !undoStack.canUndo;
	redo.disabled = !undoStack.canRedo;
	undo.title = undoStack.canUndo
		? `Undo ${undoStack.undoLabel} (Cmd/Ctrl+Z)`
		: 'Nothing to undo (Cmd/Ctrl+Z)';
	redo.title = undoStack.canRedo
		? `Redo ${undoStack.redoLabel} (Cmd/Ctrl+Shift+Z)`
		: 'Nothing to redo (Cmd/Ctrl+Shift+Z)';
}

/**
 * Whether a slow solve has switched auto-run off for now.
 *
 * Re-running on every keystroke's commit is only pleasant while a solve is
 * quick, so a slow one turns it off until the next run is asked for by hand.
 * Scoped to the solver it was measured under: the whole point of the SciPy
 * solvers is that they are an independent implementation rather than a fast
 * one, and a single slow run under one of them used to turn auto-run off for
 * the rest of the session -- including after switching back to a solver that
 * takes milliseconds.
 */
function autoRunHeld() {
	if (state.lastSolveMs <= 1500) return false;
	return (state.raw?.simulation?.solver ?? DEFAULT_SOLVER) === state.lastSolveSolver;
}

/** The one place an auto-run is armed, so everything that waits on one agrees. */
function scheduleAutoRun() {
	clearTimeout(autoRunTimer);
	autoRunTimer = setTimeout(() => { autoRunTimer = null; runSimulation(); }, 350);
}

// --- what the equations work out to at the start ----------------------------

/**
 * How long working the values out may take before it stops doing it by itself.
 *
 * The whole model has to be built to evaluate any of it, and building is the
 * expensive half: a millisecond or two on the bundled examples, about 100 ms
 * on an imported model of 1,141 blocks, 330 ms on ERICA's 30 blocks over a
 * thousand nuclides each, 2.4 s on a landscape model of 4,278, and 2.2 s on
 * the largest imported assessment (798 compartments over 54 nuclides). Size is
 * no guide -- those ERICA models are the smallest in the corpus by block count
 * and among the slowest to build -- so the cost is measured once per model and
 * the answer remembered, which is what `importblocks.js` does with its own
 * build check and for the same reason.
 *
 * It is done in a worker of its own (`previewWorker`), so the page does not
 * stop while it happens; what the budget saves is a core kept busy after every
 * edit. On the page -- where a worker cannot be had -- it stops the page, and
 * the budget is the old one.
 */
const START_BUDGET = 3000;
const START_BUDGET_ON_PAGE = 400;

/**
 * The values, and what they were worked out from: which worker build, and the
 * blocks read out of it so far -- `null` for one that has no values.
 */
let startValues = { model: null, rev: -1, id: 0, answers: null, at: null };
/** What the last attempt cost, where, and which model that was. */
let startCost = { model: null, ms: 0, budget: START_BUDGET };
let startTimer = null;

/**
 * The worker the values are worked out in: one of its own, beside the run's,
 * so that neither waits for the other. Started when first asked, and put down
 * if it fails, for the page to do the work itself.
 */
let preview = null;

function previewWorker() {
	if (preview) return preview.worker ? preview : null;
	try {
		const w = new Worker(new URL('../worker/sim-worker.js', import.meta.url), { type: 'module' });
		preview = { worker: w, seq: 0, waiting: new Map() };
		w.onmessage = (ev) => {
			const m = ev.data;
			const key = `${m?.type}:${m?.id}`;
			const answer = preview?.waiting.get(key);
			if (!answer) return;
			preview.waiting.delete(key);
			answer(m);
		};
		w.onerror = () => {
			// Answered with nothing, and not asked again: the page does it.
			const waiting = preview?.waiting ?? new Map();
			preview = { worker: null, seq: 0, waiting: new Map() };
			for (const answer of waiting.values()) answer(null);
			try { w.terminate(); } catch { /* gone either way */ }
		};
	} catch {
		preview = { worker: null, seq: 0, waiting: new Map() };
	}
	return preview.worker ? preview : null;
}

/** One question to the worker, answered by the reply of the same type and id -- or null. */
function askPreview(p, message) {
	return new Promise((resolve) => {
		p.waiting.set(`${message.type}:${message.id}`, resolve);
		p.worker.postMessage(message);
	});
}

/**
 * The values as they stand, or null while they are being worked out.
 *
 * Deliberately not computed here: this is called from the panel renderers,
 * which run on every edit and on every keystroke in the block search box. A
 * stale answer schedules the work and says nothing until it is done.
 */
function startValuesNow() {
	if (!state.raw) return null;
	if (startValues.model === state.raw && startValues.rev === state.rev) {
		return startValues;
	}
	scheduleStartValues();
	return null;
}

function scheduleStartValues() {
	clearTimeout(startTimer);
	// Measured once per model and then left alone: a model that takes two
	// seconds to build is a model where this would cost two seconds on every
	// edit, which is not worth one line under a box. Kept against the model it
	// was measured on, because a landscape model's cost says nothing about the
	// two-compartment one pasted into the JSON tab after it -- and a model
	// arrives by more routes than `setModel`.
	if (startCost.model === state.raw && startCost.ms > startCost.budget) return;
	startTimer = setTimeout(async () => {
		startTimer = null;
		if (!await computeStartValues()) return;
		// Written into the lines that are already on screen rather than by
		// rendering the panels again: re-rendering the settings dialog would
		// take the focus out of whatever box was being typed into.
		fillStartValues(document, startValueFor);
		// The exception is the Information view, where the answer decides what
		// rows there are to write into -- a block carries a value per index,
		// and the list of them cannot be filled in if it was never built. That
		// card holds nothing that can be typed into, so it is built again.
		renderInfoCard();
	}, 400);
}

/** @returns {Promise<boolean>} whether there is anything new to write out */
async function computeStartValues() {
	const model = state.raw;
	const rev = state.rev;
	const p = previewWorker();
	if (!p) return computeStartValuesHere(model, rev);
	// The model as the worker is to read it: the undo stack's text, which is
	// the model as it stands and has been written out already -- stringifying
	// it again was 70 ms of a large model's opening.
	const text = typeof undoStack.cur === 'string' ? undoStack.cur : JSON.stringify(model);
	const id = ++p.seq;
	const reply = await askPreview(p, { type: 'start-values', id, text });
	if (!reply) return computeStartValuesHere(model, rev);
	// A model opened, pasted or undone while the worker built this one: the
	// answer is about a model nobody is looking at, and its cost says nothing
	// about the one that replaced it.
	if (state.raw !== model || state.rev !== rev) return false;
	startCost = { model, ms: reply.ms, budget: START_BUDGET };
	startValues = { model, rev, id, answers: reply.fault ? null : new Map(), at: null };
	noteBuildProblem(reply.fault ? Object.assign(new Error(reply.fault.message), reply.fault) : null);
	sayStartBudget();
	return true;
}

/** The same, on the page, where no worker can be had: it stops the page while it builds. */
async function computeStartValuesHere(model, rev) {
	let at = null;
	// Loaded when something first asks, like the main-thread solver above and
	// for the same reason: this pulls in the whole builder, and an editor that
	// nobody has asked a value of should not be waiting for it to parse.
	let valuesAtStart;
	try {
		({ valuesAtStart } = await import('../sim/atstart.js'));
	} catch {
		// It will not appear on a second attempt either, and the panels ask
		// again on every render: without latching, a failed fetch is a request
		// every 400 ms for the rest of the session.
		startCost = { model, ms: Infinity, budget: START_BUDGET_ON_PAGE };
		return false;
	}
	// The first of those imports is a real fetch, and a model can be opened,
	// pasted or undone while it is in flight.
	if (state.raw !== model || state.rev !== rev) return false;
	// Timed from here, so what is measured is the work rather than the fetch.
	const started = Date.now();
	let fault = null;
	try {
		at = valuesAtStart(new Project(structuredClone(model)));
	} catch (e) {
		// A model that will not build has no values; a fault the builder
		// names is one the run would stop on -- see `noteBuildProblem`.
		at = null;
		fault = e;
	}
	startCost = { model, ms: Date.now() - started, budget: START_BUDGET_ON_PAGE };
	startValues = { model, rev, id: 0, answers: null, at };
	noteBuildProblem(fault);
	sayStartBudget();
	return true;
}

/**
 * Said once, when it gives up, because a line that quietly stops appearing
 * reads as a fault rather than as a decision.
 */
function sayStartBudget() {
	if (startCost.ms <= startCost.budget) return;
	flash(`Working out what the equations come to at the start takes `
		+ `${fmtTime(startCost.ms / 1000)} s on this model, which is too `
		+ `long to repeat after every edit — so those lines will not be `
		+ `brought up to date again. A run shows the same numbers, in the `
		+ `table's first row.`, 'info');
}

/** Blocks asked about since the last question went to the worker. */
let startAsking = null;

/**
 * Asks the worker for one block's values, with every other asked for in the
 * same moment: a settings dialog asks for each of its boxes, the Information
 * view for its block, and one message carries them all.
 */
function askStartOf(name) {
	const sv = startValues;
	if (!sv.answers || !preview?.worker) return;
	if (startAsking) { startAsking.names.add(name); return; }
	startAsking = { names: new Set([name]) };
	queueMicrotask(async () => {
		const names = [...startAsking.names];
		startAsking = null;
		const reply = await askPreview(preview, { type: 'start-of', id: sv.id, names });
		// For the build that was asked, and no other.
		if (startValues !== sv || !reply?.answers) return;
		for (const [n, found] of reply.answers) sv.answers.set(n, found ?? null);
		fillStartValues(document, startValueFor);
		renderInfoCard();
	});
}

/**
 * One equation's values at the start, for the line under its box.
 *
 * `key` is the property the equation was written in -- `initial`, `equation`,
 * `rate`, `target`, `delay`, `first`, `second` -- which is what the settings
 * dialog already calls the field. Without a key it is the block's own value,
 * which is what the chart would draw for it. Null while it is being worked
 * out, and the line is written when it is.
 */
function startValueFor(name, key = null) {
	const sv = startValuesNow();
	if (!sv) return null;
	let found;
	if (sv.at) {
		found = sv.at.of(name);
	} else if (sv.answers) {
		if (!sv.answers.has(name)) {
			askStartOf(name);
			return null;
		}
		found = sv.answers.get(name);
	}
	if (!found) return null;
	if (!key) return found.own;
	return found.fields.get(key) ?? null;
}

/**
 * The problems that belong to a named block, one message each.
 *
 * The diagram marks a block rather than listing its faults, so a block with
 * three broken fields gets one badge and the first message -- with the count,
 * since "and 2 more" on the badge is the difference between fixing one field
 * and thinking you are done.
 */
function marksByName() {
	const entries = state.problems
		.filter((p) => p.where)
		.map((p) => ({ where: p.where, level: 'error', message: `${p.what}: ${p.message}` }));
	// The warnings too, in amber: a unit that disagrees with its equation, a
	// far-field release delivered where it is counted twice. The model runs
	// with them, which is why they are a different colour, and not why they
	// should be harder to find.
	//
	// Always, whatever `show_warning_list` says. Putting the summary away is
	// a decision about a panel across the top of the window; a glyph beside a
	// name costs nothing and is how a warning is found once the list is gone.
	for (const w of state.warnings) {
		entries.push({ where: w.name, level: 'warning', message: w.message });
	}
	for (const w of state.runWarnings) {
		entries.push({ where: w.block, level: 'warning', message: `After the last run: ${w.message}` });
	}
	// And a fault found by building the model -- by the last run, or by the
	// build behind the values at the start -- when it names a block. Those
	// used to reach the strip and nothing else: a waste package whose rate
	// would not compile looked like every other block on the diagram, in the
	// tree and in its own settings, however long the strip said otherwise.
	for (const p of [state.runProblem, state.buildProblem]) {
		if (p?.where) entries.push({ where: p.where, level: 'error', message: `${p.what}: ${p.message}` });
	}
	// Carried up to every sub-system on the way down to the block, so a
	// fault in `foo.bar.Expr` is a mark on `foo` at the top level, on
	// `foo.bar` inside `foo`, and on `Expr` inside `foo.bar`. See
	// `edit.propagateMarks`.
	return ed.propagateMarks(entries);
}

/**
 * What is wrong with the model, and where.
 *
 * Two sources, kept apart because they answer at different times: the
 * equations, which can be scanned from the model as it stands, and the last
 * run, whose failure is a fact about an attempt rather than about the text.
 * Building a `Project` is included in the first because a great deal of what
 * makes a model unrunnable -- a missing half-life, a bad time span, an entry
 * keyed by a dimension its block does not have -- is only found there, and it
 * names the block it is about.
 */
/**
 * Everything wrong with the model, found and shown.
 *
 * `rail` is false where the caller is about to render it anyway. That is the
 * edit path: `republish` scans and then calls `renderEditorViews`, which
 * renders the rail -- so the rail, and the tree of every block in the model
 * inside it, was being built twice for one edit. On a model of 1,350 blocks
 * that was 104 ms and then 29 ms of the 206 an edit took. The other two
 * callers -- the JSON tab's Apply, and opening a file -- scan *after* they
 * render, because a model can arrive with something already wrong in it, and
 * those still want the rail brought up to date.
 */
function rescanProblems({ rail = true } = {}) {
	const found = ed.allEquationProblems(state.raw).map((p) => ({
		kind: 'equation',
		where: p.name,
		what: `${p.field}${p.index ? ` at ${Object.values(p.index).join(' · ')}` : ''}`,
		message: p.message,
	}));
	// The simulation settings, keyed by setting so the panel can mark the
	// field rather than only saying that the model will not run.
	for (const p of ed.simulationProblems(state.raw)) {
		found.push({
			kind: 'simulation',
			where: null,
			// Named as the panel names it, and the key kept for the field that
			// has to be marked.
			what: SIM_LABELS[p.key] ?? p.key,
			key: p.key,
			message: p.message,
		});
	}
	// An availability that cannot be worked out is a flux that cannot be
	// worked out. Errors rather than warnings, for that reason.
	for (const p of availabilityProblems(state.raw)) {
		found.push({ kind: 'availability', where: p.name, what: p.field, message: p.message });
	}
	// A switch time that cannot be resolved costs accuracy at one corner and
	// nothing else, so those are warnings rather than errors -- they go in
	// with the rest of the warnings below.

	// A transport whose chain cannot be built: no End, an N the run cannot
	// know before it starts. Named by the block where there is one, and by
	// the sub-system otherwise.
	for (const p of ed.transportProblems(state.raw)) {
		found.push({
			kind: 'transport',
			where: p.name ?? p.path,
			what: `transport ${ed.baseName(p.path)}`,
			message: p.message,
		});
	}
	// Only worth asking once the rest is sound: a model with `0q` in it, or a
	// zero tolerance, fails to build for that reason too, and saying so twice
	// is noise.
	if (!found.length) {
		try {
			new Project(structuredClone(state.raw));
		} catch (e) {
			found.push({
				kind: 'model',
				where: e.blockName ?? null,
				what: e.name === 'ValidationError' ? 'the model' : e.name,
				message: e.message,
			});
		}
	}
	state.problems = found;
	// Once per scan: the marks read this, and so does the strip.
	// Once for the whole edit: the warnings are built from it, and so is the
	// rail's info card, which used to walk every block in the model a second
	// time for the same list.
	state.unitProblems = ed.allUnitProblems(state.raw);
	state.warnings = ed.modelWarnings(state.raw, { unitProblems: state.unitProblems });
	state.marks = marksByName();
	renderProblems();
	renderWarningButton();
	updateDirtyBadge();
	// The marks go out from here, whatever order the callers render in: a
	// model that arrives from a file or the JSON tab is drawn before it is
	// scanned, and a diagram that only took its marks with the render kept
	// the empty set the scan had not yet replaced.
	graph?.setProblems(state.marks);
	if (rail) renderRail();
	return found;
}

function updateDirtyBadge() {
	// The dot keeps its space whether or not it is shown, so the button never
	// changes width. `hidden` would remove it from the layout, and the button
	// shrank by the width of the dot every time a run started.
	const blocked = state.problems.length > 0;
	$('#dirty').classList.toggle('is-on', state.dirty || blocked);
	// The dot is decorative (aria-hidden), so the state has to be said
	// somewhere a screen reader will reach: the button's own label. And there
	// are three states, not two -- unrun, and unrunnable.
	// Which run this is. There are two now, and the button that says only
	// `Run` is the deterministic one -- which is not obvious to anybody who has
	// just done a probabilistic one and wants it again, and was worth a
	// sentence rather than a guess.
	const what = 'Integrate the model once, at the values it holds '
		+ '(Cmd/Ctrl+Enter). A probabilistic run is its own button, under '
		+ 'Uncertainty in the left panel.';
	$('#run').title = blocked
		? `${what} — ${state.problems.length === 1
			? 'the model has a problem' : `the model has ${state.problems.length} problems`}`
			+ ' that must be fixed first; see the strip under the tabs'
		: state.dirty
			? `${what} — the model has changed since the last run`
			: what;
	// And said on the button itself once a probabilistic run stands, where the
	// two are genuinely easy to confuse.
	$('#run').firstChild.textContent = currentProb() ? 'Run once' : 'Run';
}

// --- errors and status ------------------------------------------------------

/**
 * One banner, above the panels, so it is visible whichever tab is open.
 *
 * There used to be a copy inside the Build panel and another inside the Chart
 * panel, and every other tab was sent to Chart to read it -- which left the
 * Matrix tab, excepted from that redirect, showing nothing at all. With one
 * banner there is nowhere for an error to hide, and no need to move you off
 * the tab you are working on.
 */
function showError({ name, message, blockName, hint }) {
	// Not if the scan already has it. A model that will not build fails the
	// same way in both places -- `rescanProblems` builds a `Project` too --
	// and "2 problems" for one mistake is worse than one, because it makes the
	// reader look for a second one.
	const already = state.problems.some((p) => p.message === message);
	const before = state.runProblem?.where ?? null;
	state.runProblem = already ? null : {
		kind: 'run',
		where: blockName ?? null,
		what: name ?? 'Error',
		message: hint ? `${message} — ${hint}` : message,
	};
	// The marks only when a block is involved, coming or going: `remark`
	// rebuilds the tree, and this runs on every failed run.
	if (before || state.runProblem?.where) remark();
	else renderProblems();
	renderStaleness();
}

function clearError() {
	// Called as every run starts, so the tree is rebuilt only when there was
	// a block marked to take the mark off.
	const before = state.runProblem?.where ?? null;
	state.runProblem = null;
	if (before) remark();
	else renderProblems();
}

/**
 * The marks drawn again, after a fault that is not the scan's arrived or
 * went: a run's, or the one the build behind the values at the start found.
 * The scan puts them out on every edit; these come between edits.
 */
function remark() {
	state.marks = marksByName();
	graph?.setProblems(state.marks);
	renderRail();
	renderProblems();
	fillSettingsProblems();
}

/** Whether the build's fault is one the strip has not already got. */
function buildProblemShown() {
	const b = state.buildProblem;
	if (!b) return false;
	return !state.problems.some((p) => p.message === b.message) && state.runProblem?.message !== b.message;
}

/**
 * What building the model for the values at the start found, filed as a
 * problem.
 *
 * That build is the one a run makes -- the same builder, without df/dy -- so
 * what stops it stops a run: an indexed setting on a slot with no such
 * dimension, an index a block cannot reach. It used to be swallowed here on
 * the grounds that the strip had it, which it did not: the strip builds a
 * `Project`, not the system, and such a fault surfaced only as the run
 * failing, long after the edit that caused it. Not a reason to refuse the
 * Run button -- the run says the same thing if it is pressed -- but said at
 * once, in the strip, on the block and in its settings.
 */
function noteBuildProblem(e) {
	const next = e && (e.name === 'BuildError' || e.blockName) ? {
		kind: 'build',
		where: e.blockName ?? null,
		what: 'will not build',
		message: e.message,
	} : null;
	const was = state.buildProblem;
	if ((was?.message ?? null) === (next?.message ?? null) && (was?.where ?? null) === (next?.where ?? null)) return;
	state.buildProblem = next;
	remark();
}

/**
 * Looked for again after an edit, once the typing stops -- or forgotten now,
 * for a model whose build costs too much to repeat on every edit, since what
 * it says is about the model before the edit and the run will say it again.
 */
function recheckBuild() {
	if (startCost.model === state.raw && startCost.ms > startCost.budget) {
		noteBuildProblem(null);
		return;
	}
	scheduleStartValues();
}

/**
 * A block's own faults, at the top of its settings: the ones in the strip
 * that name it, the scan's and the last build's alike. Filled in place, like
 * the values at the start, so that a fault found after the dialog was drawn
 * does not rebuild it under the box being typed into.
 */
function fillSettingsProblems() {
	for (const box of document.querySelectorAll('.settings-problems')) {
		const name = box.dataset.block;
		const mine = [
			...state.problems,
			...(state.runProblem ? [state.runProblem] : []),
			...(buildProblemShown() ? [state.buildProblem] : []),
			...state.runWarnings.map((w) => ({ where: w.block, what: 'After the last run', message: w.message })),
		].filter((p) => p.where === name);
		box.replaceChildren(...mine.map((p) => el('p', { className: 'settings-problem' },
			el('b', {}, p.kind === 'run' ? 'The last run failed here. ' : p.kind === 'build' ? 'This will not build. ' : `${p.what}: `),
			// The block's name is the dialog's title already.
			String(p.message ?? '').startsWith(`${name}: `) ? p.message.slice(name.length + 2) : p.message)));
		box.hidden = !mine.length;
	}
}

/**
 * The strip above the panels: what is wrong with the model, until it is not.
 *
 * This replaced a notice at the bottom of the window that faded after seven
 * seconds and vanished if you clicked it. A model with `0q` typed into a
 * compartment would then sit there unrunnable with two things on screen saying
 * so -- a dot on the Run button, and a red border on one field in one panel of
 * one tab -- while the Chart tab went on showing the results of the last model
 * that worked. Whatever else this strip does, it does not go away on its own.
 *
 * Each problem names the block it is in and is a button to it: the strip is
 * above every tab, so the way to a broken equation should not depend on which
 * tab you were on when it broke.
 */
function renderProblems() {
	const box = $('#error');
	if (!box) return;
	const all = [...state.problems, ...(state.runProblem ? [state.runProblem] : []),
		...(buildProblemShown() ? [state.buildProblem] : [])];
	// The warnings are marked on the diagram and in the tree -- amber, with a
	// count carried up to every sub-system above them -- and until now that
	// was the only place they were said at all: a badge on `NearField`, a
	// tooltip if you found it, and nothing to read. A model can carry ten unit
	// warnings and look, from the outside, as though something is wrong with
	// it and the program will not say what.
	//
	// So they are listed here too, under the problems when there are any and
	// on their own when there are not, in their own colour and with their own
	// sentence: the model runs, and these are worth a look.
	//
	// Under the problems *when there are any* is the whole of it, and for a
	// while this said the opposite: warnings were dropped whenever the model
	// had an error. That left the ⚠ button doing nothing -- a model with both
	// showed the button, because warnings existed and were put away, and
	// clicking it set the switch, listed no warnings, and then hid the button
	// as well, since the warnings were no longer put away. Two of the three
	// things on screen changed and the one that was asked for did not.
	//
	// Switchable: a model whose warnings have been read and decided about
	// should not say them again on every edit. The ⚠ button in the header is
	// the way back -- it is only there while this is off -- and the marks
	// stay on the diagram and in the tree either way.
	const warnings = ed.view(state.raw).show_warning_list === false
		? []
		: [...state.warnings.map((w) => ({
			where: w.name,
			what: w.field ?? 'units',
			message: w.message,
			// Not every warning is about a block. One about the output grid
			// has no name to link to and an editor instead; `goto` says which.
			goto: w.goto ?? null,
			warning: true,
		})), ...state.runWarnings.map((w) => ({
			where: w.block, what: 'last run', message: w.message, warning: true,
		}))];
	const rows = [...all, ...warnings];
	box.replaceChildren();
	box.hidden = !rows.length;
	box.classList.toggle('is-warning', !all.length && warnings.length > 0);
	document.body.classList.toggle('has-problems', all.length > 0);
	if (!rows.length) return;

	const head = all.length
		? el('div', { className: 'problems-head' },
			el('b', {}, all.length === 1 ? '1 problem' : `${all.length} problems`),
			el('span', { className: 'problems-what' },
				state.problems.length
					? 'the model will not run until this is fixed'
					: state.runProblem ? 'from the last run' : 'the model will not build as it stands'),
			// What else is in the list, when there is something else. The
			// count above is of problems and says so, and a reader looking at
			// nine rows under a heading that says three is owed the other six.
			warnings.length
				? el('span', { className: 'problems-also' },
					`· ${warnings.length} warning${warnings.length === 1 ? '' : 's'}`)
				: null)
		: el('div', { className: 'problems-head' },
			el('b', {}, warnings.length === 1 ? '1 warning' : `${warnings.length} warnings`),
			el('span', { className: 'problems-what' },
				'the model runs; these are worth a look'));
	// The same open-and-close control the foot of the list carries, on the
	// header as well -- which is sticky, so it is reachable whether the list
	// is six rows or thirty. The one at the foot is at the end of a scrolling
	// box, which is the wrong end of a list you are trying to close.
	const MOST = 6;
	if (rows.length > MOST) head.append(expander(rows.length, MOST, box, 'problems-head-more'));
	// Only the warnings can be switched off, so the button is there whenever
	// warnings are being shown -- including under a problem, which is the case
	// it used to miss: the list could show them and offer no way to put them
	// away again until the error was fixed. A model that will not run still
	// has to say so, and nothing here hides that: `Hide` has only ever hidden
	// the warnings.
	if (warnings.length) {
		const hide = el('button', {
			className: 'problems-hide', type: 'button',
			title: 'Put this list away — the ⚠ button in the header brings it '
				+ 'back, and the marks stay on the diagram and in the tree',
		}, 'Hide');
		hide.addEventListener('click', () => {
			ed.setView(state.raw, { show_warning_list: false });
			// Saved with the model and undoable, but not a reason to re-run:
			// nothing about the numbers has changed.
			modelChanged({ layoutOnly: true });
			flash(`${warnings.length} warning${warnings.length === 1 ? '' : 's'} put away. `
				+ 'The ⚠ button in the header brings the list back.', 'info');
		});
		head.append(hide);
	}
	box.append(head);

	// Long lists are capped: a model whose nuclide list has just been renamed
	// can have a hundred broken equations, and a strip a hundred rows tall is
	// a strip nobody reads. Capped, not truncated -- the rest are a click
	// away, and the strip scrolls within its own height rather than pushing
	// the panels down the window.
	const shown = state.problemsExpanded ? rows : rows.slice(0, MOST);
	for (const p of shown) {
		const row = el('div', { className: `problem${p.warning ? ' is-warning' : ''}` });
		if (p.where) {
			const go = el('button', {
				className: 'problem-where', type: 'button',
				title: `Show ${p.where}`,
			}, p.where);
			go.addEventListener('click', () => {
				const found = ed.findBlock(state.raw, p.where);
				// A problem may be about a sub-system rather than a block --
				// a transport with no End -- and that is a place to go too.
				if (!found && !ed.systems(state.raw).includes(p.where)) return;
				setSelection(found ? { kind: found.kind, name: p.where } : { kind: 'system', name: p.where });
				// The diagram is where a block is, so a problem about one goes
				// there. The tree and the reading view are in the left panel
				// and are beside every tab, but selecting a block and leaving
				// the reader on the JSON says nothing about where it is.
				if (state.tab !== 'build' && state.tab !== 'matrix') selectTab('build');
			});
			row.append(go);
		} else if (p.goto && GOTO[p.goto]) {
			// A warning about the model rather than about a block: the run's
			// output grid has no name on the diagram, so the row links to the
			// editor that answers it instead, and that link is the first
			// column -- the one a block's name would have been in.
			const go = el('button', {
				className: 'problem-where', type: 'button',
				title: `Open ${p.what}`,
			}, p.what);
			go.addEventListener('click', () => GOTO[p.goto]());
			row.append(go);
		}
		// The middle column is what the fault is about -- a field name, or
		// `units`. A row whose link is already that word leaves it empty
		// rather than saying it twice, and keeps the column so the messages
		// down the strip start in the same place.
		const linked = !p.where && p.goto && GOTO[p.goto];
		row.append(
			el('span', { className: 'problem-what' }, linked ? '' : p.what),
			el('span', { className: 'problem-msg' }, p.message),
		);
		box.append(row);
	}
	if (rows.length > MOST) box.append(expander(rows.length, MOST, box, 'problem-more'));
}

/**
 * The control that opens the strip out and closes it again.
 *
 * Two of them, on the header and at the foot of the list, because a list long
 * enough to need one is long enough that the far end of it is a scroll away --
 * and closing a list you cannot see the end of should not require finding the
 * end of it.
 */
function expander(total, most, box, className) {
	const more = el('button', { className, type: 'button' },
		state.problemsExpanded
			? `Show the first ${most}`
			: `and ${total - most} more — show all ${total}`);
	more.addEventListener('click', () => {
		state.problemsExpanded = !state.problemsExpanded;
		renderProblems();
		// Back to the top when closing: the strip scrolls, and what was under
		// the pointer is no longer there.
		if (!state.problemsExpanded) box.scrollTop = 0;
	});
	return more;
}

/**
 * The ⚠ in the header: there only while the model has warnings and their list
 * has been put away.
 *
 * A count rather than a bare glyph, because the question it answers is whether
 * anything has changed since they were put away -- and it is the way back to
 * the list, which is otherwise a menu item on a canvas you may not be looking
 * at.
 */
function renderWarningButton() {
	const button = $('#warnings');
	if (!button) return;
	const n = state.warnings.length;
	const away = ed.view(state.raw).show_warning_list === false;
	button.hidden = !(n && away);
	if (button.hidden) return;
	button.textContent = `⚠ ${n}`;
	button.title = `${n} warning${n === 1 ? '' : 's'} in this model, `
		+ 'not listed — click to show them again';
}

let statusTimer = null;
/** How long a notice stays. A warning is worth reading; news is not. */
const NOTICE_LIFE = { info: 4200, warn: 7500 };
const NOTICE_FADE = 180;

/**
 * Says what just happened, over the bottom of the window.
 *
 * A notice is out of the layout (see `#flash` in the stylesheet): it arrives
 * because of something that was just clicked, and a message that pushes the
 * panels down a line as it appears makes the interface jump under the hand
 * that caused it.
 */
function flash(message, tone = 'info') {
	const n = notice();
	n.textContent = message;
	n.dataset.tone = tone;
	n.title = 'Click to dismiss';
	n.classList.remove('is-going');
	// Re-triggered so a second notice arrives as visibly as the first, rather
	// than the text changing under a panel that is already there.
	if (!n.hidden) { n.hidden = true; void n.offsetHeight; }
	n.hidden = false;
	clearTimeout(statusTimer);
	statusTimer = setTimeout(() => {
		n.classList.add('is-going');
		statusTimer = setTimeout(() => {
			n.hidden = true;
			n.classList.remove('is-going');
		}, NOTICE_FADE);
	}, NOTICE_LIFE[tone] ?? NOTICE_LIFE.info);
}

/**
 * The notice element, put wherever it can be read.
 *
 * Its home is the footer, but a modal dialog paints its backdrop over
 * everything behind it -- and a message raised *from* the dialog, which is
 * most often a name or a unit being refused, is exactly the one that has to be
 * legible. So while a dialog is open the notice moves into it, where it is
 * above the backdrop rather than under it.
 *
 * Held in a variable rather than looked up, because the dialog is removed from
 * the document when it closes: the notice is brought home first, and the
 * `isConnected` check is the belt to that braces.
 */
let noticeEl = null;
function notice() {
	noticeEl ??= $('#flash');
	const footer = $('#app > footer');
	if (!noticeEl.isConnected) footer.append(noticeEl);
	// A modal one: a floating window has no backdrop over the footer.
	const home = document.querySelector('dialog:modal') ?? footer;
	if (noticeEl.parentNode !== home) {
		home.append(noticeEl);
		// Registered after the dialog's own close handler, which is what
		// removes it, so this runs with the element already detached -- and
		// appending it moves it back out.
		if (home !== footer) {
			home.addEventListener('close', () => footer.append(noticeEl), { once: true });
		}
	}
	return noticeEl;
}

/** Dismissed by clicking it: a notice you have read is in the way. */
function wireFlash() {
	const n = notice();
	n.addEventListener('click', () => {
		clearTimeout(statusTimer);
		n.hidden = true;
		n.classList.remove('is-going');
	});
}

/**
 * How the Jacobian was obtained. Worth a line of its own: it is the difference
 * between n evaluations of the model per step and one, and between a dense
 * factorisation and a sparse one -- which on a large model is the difference
 * between minutes and seconds.
 */
function describeJacobian(p) {
	const j = p.jacobian;
	if (j?.asked) return `differenced, ${p.stats.sparse ? 'sparse' : 'dense'}`;
	if (!j?.available) return 'differenced';
	return `analytic, ${p.stats.sparse ? 'sparse' : 'dense'}`;
}

function jacobianDetail(p) {
	const j = p.jacobian;
	if (j?.asked) {
		return 'df/dy is differenced through the pattern of the generated one, as the '
			+ 'Jacobian setting under Advanced settings asks: '
			+ `${j.colours} evaluation${j.colours === 1 ? '' : 's'} of the model per Jacobian, `
			+ `not ${p.stateCount}. `
			+ (p.stats.sparse ? `Factorised sparsely, fill ${p.stats.fill}.` : 'Factorised densely.');
	}
	if (!j?.available) {
		return 'df/dy is approximated by finite differences'
			+ (j?.reason ? `, because ${j.reason}` : '')
			+ '. Every column costs one evaluation of the model.';
	}
	const bits = [
		`${j.nnz} non-zero entries (${(j.density * 100).toFixed(1)}% of the matrix)`,
		`${j.colours} seed${j.colours === 1 ? '' : 's'} per evaluation, not ${p.stateCount}`,
		j.constant
			? 'constant, so it is built once for the whole run'
			: 're-evaluated when the Newton iteration stalls',
	];
	if (j.budgetRows === 'diagonal') bits.push('the mass-balance budgets\u2019 rows at their diagonal, which is all a Newton iteration needs');
	if (j.budgetRows === 'exact') bits.push('the mass-balance budgets\u2019 rows generated whole, which this solver needs');
	if (p.stats.sparse) bits.push(`factorised sparsely, fill ${p.stats.fill}`);
	else bits.push('factorised densely: at this size that is the faster of the two');
	return `Generated from the equations. ${bits.join('. ')}.`;
}

/** The footer's word on what the constraint held: the worst few, by share of steps. */
/** What a split run was, for the status line's tooltip. */
function splitDetail(split) {
	if (!split) return '';
	if (!split.used) return `Not split: ${split.why}.`;
	// One line per worker: each solved its share of the parts together, at
	// its own steps.
	const parts = split.parts ?? split.jobs.length;
	const lines = [`Solved in ${parts} independent parts on ${split.workers} cores, `
		+ `each core\u2019s share at its own steps: ${split.why}.`];
	if (split.gain) lines.push(`About ${split.gain.toFixed(1)}\u00d7 the speed of a whole solve, by this machine\u2019s estimate.`);
	lines.push('');
	for (const j of split.jobs.slice(0, 12)) {
		lines.push(`${j.materials.slice(0, 6).join(', ')}${j.materials.length > 6 ? `, and ${j.materials.length - 6} more` : ''}`
			+ ` \u2014 ${j.states.toLocaleString()} states, ${j.nsteps ?? '?'} steps, ${Math.round(j.solveMs ?? 0)} ms`);
	}
	if (split.jobs.length > 12) lines.push(`and ${split.jobs.length - 12} more cores`);
	lines.push('', 'The parts agree with a whole solve to within the tolerance, not to the last digit.');
	return lines.join('\n');
}

function heldSummary(held) {
	if (!held?.length) return null;
	const pct = (h) => `${Math.max(1, Math.round(h.fraction * 100))}%`;
	const shown = held.slice(0, 2).map((h) => `${h.label} ${pct(h)}`);
	const more = held.length - shown.length;
	return shown.join(', ') + (more ? ` and ${more} more` : '');
}

/** The audit as a tooltip: the verdict, then a line per family. */
function balanceDetail(a) {
	const lines = describeAudit(a, { timeUnit: state.raw?.simulation?.time_unit ?? '' });
	return 'The mass-balance audit: at every output time, what each family of compartments '
		+ 'holds against what came in, went out, decayed, grew in, or was moved by an explicit '
		+ 'term. Relative to the largest amount the family held or moved. The solver integrates '
		+ 'the budgets with the inventories, so this closes to within its tolerance — round-off '
		+ 'with an explicit solver, about the relative tolerance with an implicit one — unless a '
		+ 'compartment was held at zero or something moved that nothing accounts for.\n\n'
		+ lines.join('\n');
}

function heldDetail(held) {
	const lines = held.map((h) => `${h.label}: ${h.steps} of the solver's steps`);
	return '"Cannot go negative" held these compartments at zero while their equations '
		+ 'pushed them below it by more than the tolerance. What is charted for them is the '
		+ 'constrained system, not what the model computes -- usually a rate with the wrong '
		+ 'sign, or a transfer draining what was never filled. Turn the setting off on the '
		+ `compartment to see what the model really does.\n${lines.join('\n')}`;
}

/**
 * The run log as text: the deterministic run on screen, the probabilistic
 * run behind it when one stands, and -- for a run opened from a results
 * archive -- the log that was saved with it, first, since that is the run's
 * own account and this page never saw it made.
 */
function runLogFor() {
	const r = state.results;
	if (!r) return '';
	const parts = [];
	if (r.storedLog?.length) {
		parts.push('--- as saved with the results ---', ...r.storedLog, '', '--- on opening ---');
	}
	parts.push(...runLogLines({ project: state.raw, payload: r, replayed: r.replayed ?? null, build: BUILD }));
	parts.push(...scenarioLogLines(ed.activeScenario(state.raw), scenarioRunsNow()));
	parts.push(...probabilisticLogLines(currentProb()));
	if (state.tornado && state.tornado.rev === state.rev) {
		parts.push(...probabilisticLogLines({
			iterations: state.tornado.points, stats: state.tornado.stats, plan: null, screen: null,
		}));
	}
	return runLogText(parts);
}

/** This model against the file it came from. */
function compareWithOpened() {
	if (!state.opened?.text) { flash('Nothing has been opened yet.', 'warn'); return; }
	const before = JSON.parse(state.opened.text);
	const diff = compareModels(before, state.raw);
	openVersionReport(diff, { before: `${state.opened.label} as opened`, after: 'this model' });
}

/** This model against another file, read the way Open reads one. */
function compareWithFile() {
	pickFile(async (file) => {
		let other;
		try {
			({ project: other } = await readModelFile(file));
		} catch (e) {
			flash(`Could not read ${file.name}: ${e?.message ?? e}`, 'error');
			return;
		}
		// The same tidying the model in front of you had on the way in, so
		// that key spellings and layout are not reported as differences.
		other = ed.migrateKeys(other);
		ed.materialiseShorthand(other);
		ed.syncDerivedUnits(other);
		const diff = compareModels(other, state.raw);
		openVersionReport(diff, { before: file.name, after: 'this model' });
	});
}

/**
 * A text file, asking where it should go: the operating system's own save
 * dialog, as Save… asks for a model, and the browser's download only where
 * there is no such dialog -- which is then said, since the file has gone
 * somewhere the reader did not choose. The ellipsis on *Save as text…* is a
 * promise that it will ask; a link-and-click download dropped the file into
 * the downloads folder without a word, which read as the button doing nothing.
 *
 * Called from the click itself: the dialog may only be opened out of one.
 */
async function saveText(name, text, what = 'Text') {
	if (typeof window.showSaveFilePicker === 'function') {
		let handle = null;
		try {
			handle = await window.showSaveFilePicker({
				suggestedName: name,
				types: [{ description: what, accept: { 'text/plain': ['.txt'] } }],
			});
		} catch (e) {
			// Cancelling is an answer: nothing is saved and nothing is said.
			if (e?.name === 'AbortError') return false;
			handle = null;
		}
		if (handle) {
			try {
				const to = await handle.createWritable();
				await to.write(text);
				await to.close();
				flash(`Saved ${handle.name}.`, 'info');
				return true;
			} catch (e) {
				showError({
					name: 'Save', message: `Could not write the file: ${e.message}`,
					hint: 'The folder may be read-only. Try again and pick another place.',
				});
				return false;
			}
		}
	}
	download(name, text, 'text/plain');
	flash(`Saved ${name} to wherever this browser puts downloads — it has no "save as" `
		+ 'dialog for a page to open.', 'info');
	return true;
}

/**
 * All of `text` onto the clipboard, and how much that was.
 *
 * Through the Clipboard API where the browser allows it, and where it refuses
 * -- a frame without the permission, an older browser -- through a selection
 * of a hidden text box, the older route. The box goes inside the open dialog:
 * a modal dialog makes everything outside it inert, and an inert box can be
 * neither selected nor copied from. Said either way, with the number of
 * lines, so that "was that all of it" is answered; a failure used to be
 * swallowed, and the reader then copied what was in view by hand.
 */
async function copyText(text, what) {
	const lines = text.split('\n').length.toLocaleString();
	try {
		await navigator.clipboard.writeText(text);
		flash(`Copied ${what} — all ${lines} lines.`, 'info');
		return true;
	} catch { /* refused; the older route below */ }
	const area = el('textarea', { value: text, readOnly: true, 'aria-hidden': 'true' });
	Object.assign(area.style, { position: 'fixed', left: '-9999px', top: '0', opacity: '0' });
	(document.querySelector('dialog:modal') ?? document.body).append(area);
	area.select();
	let ok = false;
	try { ok = document.execCommand('copy'); } catch { ok = false; }
	area.remove();
	if (ok) flash(`Copied ${what} — all ${lines} lines.`, 'info');
	else flash('This browser would not copy it. Click in the text, press ⌘A (Ctrl+A) to select '
		+ 'all of it, and copy that.', 'warn');
	return ok;
}

/**
 * A block of text to read in a dialog: all of it selectable at once. ⌘A (or
 * Ctrl+A) inside it selects the text and not the page around it, which is
 * what anybody copying a log by hand reaches for.
 */
function logPre(text) {
	const pre = el('pre', { className: 'runlog', tabIndex: 0 }, text);
	pre.addEventListener('keydown', (ev) => {
		if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'a') {
			ev.preventDefault();
			const range = document.createRange();
			range.selectNodeContents(pre);
			const sel = window.getSelection();
			sel.removeAllRanges();
			sel.addRange(range);
		}
	});
	return pre;
}

/**
 * Fills the window with a dialog, and puts it back: for a log or a report
 * that is longer than the box it opened in. The text grows with the dialog.
 *
 * The dialog is found from the button when it is pressed: the button is made
 * while the dialog is being built, before there is a dialog to hand it.
 */
function expandButton() {
	const b = el('button', { type: 'button', className: 'ghost', title: 'Fill the window with this, and back' }, 'Expand');
	let was = null;
	b.addEventListener('click', () => {
		const d = b.closest('dialog');
		if (!d) return;
		const body = d.querySelector('.modal-body');
		if (!was) {
			was = {
				left: d.style.left, top: d.style.top, width: d.style.width, maxHeight: d.style.maxHeight,
				bodyHeight: body.style.height, bodyMax: body.style.maxHeight,
			};
			const head = Math.ceil(d.querySelector('.modal-head')?.getBoundingClientRect().height ?? 60);
			Object.assign(d.style, { left: '16px', top: '16px', width: 'calc(100vw - 32px)', maxHeight: 'calc(100vh - 32px)' });
			body.style.height = body.style.maxHeight = `calc(100vh - 34px - ${head}px)`;
			d.classList.add('is-expanded');
			b.textContent = 'Shrink';
		} else {
			Object.assign(d.style, { left: was.left, top: was.top, width: was.width, maxHeight: was.maxHeight });
			body.style.height = was.bodyHeight;
			body.style.maxHeight = was.bodyMax;
			d.classList.remove('is-expanded');
			b.textContent = 'Expand';
			was = null;
		}
	});
	return b;
}

/** The version report, as a dialog with the text in it. */
function openVersionReport(diff, labels) {
	const text = reportLines(diff, labels).join('\n');
	const modal = openModal({
		info: dialogInfo('version-report'),
		title: 'Version report',
		subtitle: diff.same ? 'No differences.' : `${versionSummary(diff)} — layout left out, comments counted`,
		build: (body) => {
			body.append(logPre(text));
			const copy = el('button', { type: 'button', className: 'ghost' }, 'Copy');
			copy.addEventListener('click', () => copyText(text, 'the report'));
			const save = el('button', { type: 'button', className: 'ghost' }, 'Save as text\u2026');
			save.addEventListener('click', () => saveText(`${slug(state.raw.name)}-versions.txt`, text, 'Version report'));
			const done = el('button', { type: 'button', className: 'primary' }, 'Close');
			done.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					'A block is matched by name; one gone under one name and back under another, otherwise unchanged, is a rename.'),
				expandButton(), copy, save, done));
		},
	});
	modal.dialog.classList.add('modal-wide');
}

function openRunLog() {
	const text = runLogFor();
	if (!text) { flash('Run the model first.', 'warn'); return; }
	const modal = openModal({
		info: dialogInfo('run-log'),
		title: 'Run log',
		subtitle: 'What this run was, in words that survive it — kept with a saved result',
		build: (body) => {
			body.append(logPre(text));
			const copy = el('button', { type: 'button', className: 'ghost' }, 'Copy');
			copy.addEventListener('click', () => copyText(text, 'the run log'));
			const save = el('button', { type: 'button', className: 'ghost' }, 'Save as text…');
			save.addEventListener('click', () => saveText(`${slug(state.raw.name)}-run-log.txt`, text, 'Run log'));
			const done = el('button', { type: 'button', className: 'primary' }, 'Close');
			done.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' }, 'Save… → Model with results writes this into the archive as well.'),
				expandButton(), copy, save, done));
		},
	});
	modal.dialog.classList.add('modal-wide');
}

/**
 * The footer's line, emptied. (The build stamp that used to stand on it is at
 * the foot of the Help tab: see `setBuildStamp` in ./help.js.)
 *
 * `#status` is a run's account of itself, so it belongs to the results and
 * goes when they do. Only `setStatus` ever wrote it, so New -- and Open, and
 * Apply on the JSON tab -- left the closed model's solver, step count and
 * timings standing under the new one's name, describing a run that no longer
 * exists and cannot be repeated from what is on screen. The log button beside
 * them still opened that run's log, which is worse than the numbers.
 */
function clearStatus() {
	$('#status')?.replaceChildren();
}

/**
 * The status line was cleared for a run and nothing has written it since.
 * See `setRunning`.
 */
let statusOwed = false;

/**
 * When the run going now started, and the timer that keeps its clock moving.
 *
 * Wall-clock time, beside the bar: the bar says how far the run has got in the
 * model's time, and this how long it has taken so far -- which on a model of
 * minutes is the number somebody waiting for it wants.
 */
const runClock = { started: 0, timer: 0, eta: null };

function startRunClock() {
	runClock.started = Date.now();
	clearInterval(runClock.timer);
	runClock.timer = setInterval(paintRunClock, 1000);
	paintRunClock();
}

function stopRunClock() {
	clearInterval(runClock.timer);
	runClock.timer = 0;
	runClock.started = 0;
	runClock.eta = null;
	paintRunClock();
}

function paintRunClock() {
	const node = $('#run-clock');
	if (!node) return;
	if (!runClock.started) {
		node.textContent = '';
		node.title = '';
		return;
	}
	const now = Date.now();
	const left = etaLeft(now);
	const e = runClock.eta;
	// Every realisation in, and the run not yet over: it is putting them
	// together, which on a large sample is seconds in its own right, and "a
	// few seconds left" through all of it would be a clock that had stopped.
	const finishing = left === 0 && e && e.done >= e.of;
	node.textContent = `started ${clockOf(new Date(runClock.started))} \u00b7 ${fmtElapsed((now - runClock.started) / 1000)}`
		+ (left == null ? '' : finishing ? ' \u00b7 all in, finishing' : ` \u00b7 ${fmtLeft(left)} left`);
	node.title = left == null ? ''
		: finishing ? `All ${e.of.toLocaleString('en-US')} are in, and are being put together.`
			: `Expected to finish at about ${clockOf(new Date(now + left))}: ${e.done.toLocaleString('en-US')} `
				+ `of ${e.of.toLocaleString('en-US')} are in, at the pace they have come in since the first, `
				+ `${fmtElapsed((e.tLast - e.t0) / 1000)} ago. An estimate, and a better one the longer the run `
				+ 'has gone on; putting them together at the end is not in it.';
}

/**
 * How much of the time a sampled run has had, at the least, before it says how
 * long it has left: an estimate from a second of evidence swings by a factor
 * of two with every report.
 */
const ETA_MIN_MS = 2000;

/**
 * A sampled run's count of realisations in, as the worker reports it, for the
 * time it has left.
 *
 * The pace is measured from the first realisation to finish, not from the
 * press of Run: everything before it -- building the model, starting the
 * cores, the first integration on each -- is paid once, and counting it as the
 * pace of the rest made the first minutes of an estimate far too long. And it
 * is the average since then rather than the latest step, so that a burst of
 * realisations landing together -- eight cores finishing their first at once
 * -- does not swing it. A tornado and a sensitivity design report the same
 * way, and are estimated the same way.
 */
function noteRealisations(done, of) {
	if (!Number.isFinite(done) || !Number.isFinite(of) || of <= 0) return;
	const now = Date.now();
	const e = runClock.eta;
	if (!e || e.run !== state.runId) {
		runClock.eta = { run: state.runId, t0: now, done0: done, tLast: now, done, of };
	} else {
		e.tLast = now;
		e.done = done;
		e.of = of;
	}
	paintRunClock();
}

/**
 * Milliseconds the sampled run has left, or null while there is too little to
 * go on. Counted down between the worker's reports -- the clock is repainted
 * every second, and a realisation can take longer than that -- and never below
 * nothing.
 */
function etaLeft(now = Date.now()) {
	const e = runClock.eta;
	if (!e || e.run !== state.runId) return null;
	return timeLeft(e, now);
}

/**
 * The arithmetic of it, on its own: `e` is `{t0, done0, tLast, done, of}` --
 * when the first report came and what it said, when the latest came and what
 * it said, and how many there are in all.
 */
export function timeLeft(e, now) {
	const spent = e.tLast - e.t0;
	const since = e.done - e.done0;
	if (spent < ETA_MIN_MS || since < 2) return null;
	if (e.done >= e.of) return 0;
	return Math.max(0, ((e.of - e.done) * spent) / since - (now - e.tLast));
}

/**
 * Time left, rounded as far as an estimate deserves: `a few seconds`,
 * `about 35 s`, `about 3 min 20 s`, `about 14 min`, `about 2 h 05 min`.
 * Seconds to the nearest five; minutes and hours rounded up, so that it does
 * not say a minute when there are ninety seconds.
 */
export function fmtLeft(ms) {
	const s = ms / 1000;
	if (s < 5) return 'a few seconds';
	// Each step decided after rounding, so that 59.9 s reads as a minute
	// rather than as `60 s`, and 59.9 min as an hour.
	const fives = Math.max(5, Math.round(s / 5) * 5);
	if (fives < 60) return `about ${fives} s`;
	const tens = Math.ceil(s / 10) * 10;
	if (tens < 600) {
		const m = Math.floor(tens / 60);
		const r = tens % 60;
		return `about ${m} min${r ? ` ${String(r).padStart(2, '0')} s` : ''}`;
	}
	const mins = Math.ceil(s / 60);
	if (mins < 60) return `about ${mins} min`;
	const five = Math.ceil(s / 300) * 5;
	return `about ${Math.floor(five / 60)} h ${String(five % 60).padStart(2, '0')} min`;
}

/** A time of day as the footer shows it: 14:05:09, whatever the locale. */
export function clockOf(when) {
	const two = (n) => String(n).padStart(2, '0');
	return `${two(when.getHours())}:${two(when.getMinutes())}:${two(when.getSeconds())}`;
}

/**
 * How long something has been going, to the second: `42 s`, `3 min 05 s`,
 * `1 h 02 min` -- the seconds dropped once there are hours, since a clock that
 * says 1 h 02 min 17 s is asking to be watched.
 */
export function fmtElapsed(seconds) {
	const s = Math.max(0, Math.floor(seconds));
	if (s < 60) return `${s} s`;
	const two = (n) => String(n).padStart(2, '0');
	if (s < 3600) return `${Math.floor(s / 60)} min ${two(s % 60)} s`;
	return `${Math.floor(s / 3600)} h ${two(Math.floor((s % 3600) / 60))} min`;
}

function setStatus(p) {
	statusOwed = false;
	const s = p.stats;
	// A model with no compartments was not integrated at all: its blocks were
	// evaluated over the output grid. Reporting a solver, a step count and a
	// Jacobian for that would all be fiction, so none of them is shown.
	const evaluated = s.integrated === false;
	// Three shapes wear the same `integrated: false`: a post-processing model
	// with expressions but no compartments, a model that is nothing but
	// constants, and a model with nothing in it at all. One sentence for all
	// three was true of the first and a small lie about the other two.
	const computed = (p.outputs ?? []).filter((o) => o.kind !== 'parameter').length;
	const nothing = !(p.outputs ?? []).length;
	// Not every solver reports every statistic; show what was measured rather
	// than printing "null".
	const parts = [
		evaluated
			? ['evaluated', nothing
				? 'nothing to work out — the output grid only'
				: computed
					? 'no compartments — algebraic blocks only'
					: 'no compartments — constants only']
			: ['solver', solverLabel(s.solver)],
		['states', evaluated ? null : p.stateCount], ['steps', s.nsteps],
		['rejected', s.nfailed], ['f evals', s.nfevals],
		// Steps the solver took without meeting the error test, because the
		// step size had already collapsed onto its smallest. Shown only when
		// there were any: a result carrying them is not wrong so much as
		// unvouched-for, and the reader should know which kind they have.
		['below tolerance', s.nbelowtol || null],
		// How many times were saved, and -- when the solver's own steps were
		// the output and there were too many to keep -- how many it took and
		// how far they were thinned. A result that is one point in three is
		// still the solver's distribution, but it is not every step, and the
		// footer is where that belongs.
		['points', s.thinnedBy
			? `${s.points} of ${s.solverPoints} steps, every ${s.thinnedBy}`
			: s.solverPoints ? `${s.points}, the solver's own` : s.points],
		['df/dy', evaluated ? null : describeJacobian(p)],
		// Compartments "cannot go negative" held at zero while the model pushed
		// them below. Shown only when there were any: the run is then the
		// projected system rather than what the equations say, and a flat
		// line at zero with nothing beside it reads as a result.
		['held at zero', heldSummary(p.heldAtZero)],
		// "compile", not "build": "build" is the program's own stamp, at the
		// foot of the Help tab and in the run log, and two different things
		// labelled the same way is worse than a longer word.
		['compile', `${p.timing.buildMs.toFixed(1)} ms`],
		// Said differently when the solve did not happen. The number is real --
		// it is how long these states took when they were solved for -- but
		// reporting it as this run's would claim time that was not spent, and
		// the reader is entitled to know why an edit to a large model came back
		// at once.
		[p.timing.reused ? 'solve' : (evaluated ? 'evaluate' : 'solve'),
			p.timing.reused
				? `not repeated — the states were already right`
				: `${p.timing.solveMs.toFixed(0)} ms`],
	].filter(([, v]) => v != null);
	// Solved in parts, or asked to be and not: the one it matters to see. An
	// automatic choice not to split is not news, and the log has it.
	const split = s.split;
	if (split?.used) {
		parts.push(['split', `${split.parts ?? split.jobs.length} parts on ${split.workers} core${split.workers === 1 ? '' : 's'}`]);
	} else if (split && split.mode === 'on') {
		parts.push(['split', 'not possible']);
	}
	// The audit, when the run carried it: whether the books close, and by how
	// much they do not.
	if (p.massBalance) {
		parts.push(['mass balance', p.massBalance.closed
			? `closes (${p.massBalance.worst.toExponential(0)})`
			: `open by ${p.massBalance.worst.toExponential(1)}`]);
	}
	const host = $('#status');
	host.replaceChildren();
	const replay = state.results?.replayed;
	if (replay) {
		// First, because it changes what every other number is about.
		const span = el('span', { className: 'stat stat-replay' }, 'realisation ',
			el('b', {}, replay.tornado
				? `tornado point ${replay.index + 1} of ${replay.iterations}`
				: `${(replay.index + 1).toLocaleString()} of ${replay.iterations.toLocaleString()}, seed ${replay.seed}`));
		span.title = 'This is one realisation of the probabilistic run, integrated again in '
			+ 'full — not the model at its own values. The inputs it used:\n'
			+ (replay.values ?? []).map((v) => `${v.name} = ${Number.isFinite(v.value) ? v.value : '—'}${v.held ? ' (held)' : ''}`).join('\n');
		host.append(span);
	}
	for (const [k, v] of parts) {
		const span = el('span', { className: 'stat' }, `${k} `, el('b', {}, String(v)));
		if (k === 'df/dy') span.title = jacobianDetail(p);
		if (k === 'solve' && p.timing.reused) {
			span.classList.add('stat-reused');
			span.title = 'This edit changed nothing the compartments depend on, so the '
				+ 'model was not integrated again: the states are the ones already '
				+ `solved for (${p.timing.solveMs.toFixed(0)} ms, when they were), and `
				+ 'everything worked out from them was worked out again.';
		}
		if (k === 'held at zero') {
			span.classList.add('stat-held');
			span.title = heldDetail(p.heldAtZero);
		}
		if (k === 'split') {
			span.classList.add('stat-split');
			span.title = splitDetail(split);
		}
		if (k === 'mass balance') {
			span.classList.add('stat-balance');
			if (!p.massBalance.closed) span.classList.add('is-open');
			span.title = balanceDetail(p.massBalance);
		}
		host.append(span);
	}
	// The scenarios run beside the selected one, whose numbers the rest of
	// this line is: how many are in, and what each came to on pointing.
	const runs = scenarioRunsNow();
	if (runs.length) {
		const current = runs.filter((e) => e.r && e.r.rev === state.results?.rev && !e.running && !e.queued);
		const span = el('span', { className: 'stat stat-scenarios' }, 'scenarios ',
			el('b', {}, `${current.length + 1} of ${runs.length + 1}`));
		span.title = scenarioLogLines(ed.activeScenario(state.raw), runs).slice(2)
			.map((l) => l.trim()).join('\n');
		host.append(span);
	}
	// The log: everything this line says and more, as text that can be kept.
	const log = el('button', { type: 'button', className: 'ghost stat-log', title:
		'The run log — the settings, the solver’s account of the run, what was held at '
		+ 'zero, and the probabilistic run if one stands — as text to copy or save. It is '
		+ 'written into a results archive too.' }, 'log');
	log.addEventListener('click', openRunLog);
	host.append(log);
}

// --- selection ---------------------------------------------------------------

/**
 * @param {{kind: string, name: string}|null} sel the block the inspector shows
 * @param {string[]|null} [picked] everything selected on the diagram, when the
 *   diagram is what changed it. Handed straight back so that echoing the
 *   selection does not collapse a group to the one block being inspected.
 */
function setSelection(sel, picked = null) {
	state.selection = sel;
	state.picked = picked ?? (sel?.name ? [sel.name] : []);
	recordVisit(sel?.name ?? null);
	// Not a step of its own -- an undo that only moved the highlight would be
	// maddening -- but it is what the next step should put back. Deleting a
	// block selects nothing on the way out, so without this, undoing the
	// deletion brought the block back and left it unselected.
	undoStack.note(viewNow());
	// Only when one thing is selected: a selection of several reaches across
	// sub-systems, and jumping the canvas to whichever was added last would
	// take it away from the rest of them.
	graph?.setSelection(sel, state.picked, { reveal: state.picked.length <= 1 });
	renderRail();
	renderMatrixView();
}

/**
 * Remembers where the selection has been, for the Information view's back and
 * forward.
 *
 * Recorded wherever the selection came from -- a click on the diagram, a row
 * in the tree, a reference followed in the Information view -- because "the
 * block I was looking at a moment ago" does not care how you got there.
 * Stepping through the trail must not itself be recorded, or back would only
 * ever return to where it started.
 */
function recordVisit(name) {
	const t = state.trail;
	if (t.moving || !name || t.seen[t.at] === name) return;
	t.seen = [...t.seen.slice(0, t.at + 1), name].slice(-50);
	t.at = t.seen.length - 1;
}

function stepTrail(by) {
	const t = state.trail;
	const to = t.at + by;
	if (to < 0 || to >= t.seen.length) return;
	const found = ed.findBlock(state.raw, t.seen[to]);
	if (!found) {
		// The block has gone since. Drop it and try the next one along.
		t.seen.splice(to, 1);
		if (to <= t.at) t.at -= 1;
		stepTrail(by);
		return;
	}
	t.at = to;
	t.moving = true;
	try {
		setSelection({ kind: found.kind, name: t.seen[to] });
	} finally {
		t.moving = false;
	}
}

/**
 * After an edit, something selected may have been renamed or removed.
 *
 * Sub-systems as well as blocks: a selection can hold both, and dropping the
 * sub-systems here emptied a mixed selection on the next edit -- the block
 * survived and the sub-system beside it quietly did not.
 */
function reconcileSelection() {
	const alive = (n) => !!ed.findBlock(state.raw, n) || ed.systems(state.raw).includes(n);
	if (state.selection && !alive(state.selection.name)) state.selection = null;
	state.picked = state.picked.filter(alive);
}

// --- editor views -------------------------------------------------------------

/**
 * The model's name and description, wherever they are shown.
 *
 * Called from renderEditorViews rather than only from setModel, because the
 * name can change from three directions -- the sidebar fields, the JSON tab's
 * Apply, and loading a file -- and a header still showing the previous name
 * looks exactly like an edit that did not take.
 */
function renderModelIdentity() {
	const name = ed.modelName(state.raw);
	const description = ed.modelDescription(state.raw);
	$('#title').textContent = name;
	$('#title').title = `${name}\n\nClick to rename`;
	// Only the first line fits a header; the rest is the tooltip.
	$('#subtitle').textContent = description.split('\n')[0];
	$('#subtitle').title = description
		? `${description}\n\nClick to edit`
		: 'Click to add a description';
	document.title = `${name} — Kompartment`;
}

/**
 * The diagram's help line, which is a view flag like the rest.
 *
 * Under the canvas rather than over it, so turning it off gives the diagram
 * six lines of height back -- which is what it is for. The flag lives in the
 * project beside `show_parameters` and the others, so it survives a save the
 * way the node positions do.
 */
function applyHelpLine() {
	const line = document.querySelector('.graph-help');
	if (line) line.hidden = !ed.view(state.raw).show_help;
}

function renderEditorViews(opts = {}) {
	applyHelpLine();
	renderModelIdentity();
	reconcileSelection();
	// A solver setting moves nothing that is drawn from the model, so the
	// views built out of its blocks are left as they are. See
	// `SOLVE_ONLY_SETTINGS`; everything else takes the whole path.
	const blocksMoved = !opts.solveOnly;
	if (blocksMoved) {
		graph?.setProject(state.raw);
		graph?.setSelection(state.selection, state.picked);
		// After the project, because setting it re-renders and the marks are
		// put on what is already drawn.
		graph?.setProblems(state.marks ?? marksByName());
	}
	renderBreadcrumb();
	// The info card shows the span and the solver, so the rail is rendered
	// either way -- but the tree of every block in it is not.
	renderRail({ tree: blocksMoved });
	if (blocksMoved) renderMatrixView();
	// Like the matrix: a panel that is not on screen is drawn when it comes
	// on screen (`selectTab` does that), not on every edit. The index-lists
	// panel rebuilt its half-life table and decay drawing per keystroke, and
	// left a ResizeObserver behind each time.
	if (state.tab === 'indexlists') renderIndexListsView();
	renderSidebar();
}

/**
 * Where in the hierarchy the diagram is looking, and the way back out.
 *
 * Hidden entirely for a model with no sub-systems, which is most of them: a
 * trail with one immovable step on it is furniture.
 */
function renderBreadcrumb() {
	const host = $('#breadcrumb');
	if (!host) return;
	const here = graph?.currentSystem ?? '';
	const paths = ed.systems(state.raw ?? {});
	if (!paths.length) {
		host.hidden = true;
		host.replaceChildren();
		return;
	}
	host.hidden = false;
	host.replaceChildren();

	const steps = [['', state.raw?.name || ed.UNTITLED]];
	let at = '';
	for (const part of here ? here.split('.') : []) {
		at = at ? `${at}.${part}` : part;
		steps.push([at, part]);
	}
	steps.forEach(([path, label], i) => {
		if (i) host.append(el('span', { className: 'crumb-sep' }, '›'));
		const last = i === steps.length - 1;
		const b = el('button', {
			type: 'button',
			title: path ? `Show ${path}` : 'Show the whole model',
		}, label);
		if (last) b.setAttribute('aria-current', 'true');
		else b.addEventListener('click', () => graph?.setSystem(path));
		host.append(b);
	});

	const inside = ed.blocksIn(state.raw, here, { deep: true }).length;
	const own = ed.blocksIn(state.raw, here).length;
	host.append(el('span', { className: 'crumb-count' },
		here
			? `${own} block${own === 1 ? '' : 's'} here, ${inside} in all`
			: `${own} block${own === 1 ? '' : 's'} at the top level, ${inside} in all`));

}

/**
 * The divider between the tree and Information.
 *
 * Both panes have a definite height and scroll inside it, rather than the rail
 * scrolling as a whole: with a model of any size the tree is hundreds of rows
 * long, and a rail that scrolled meant reading a block's equation and then
 * losing it to find the next block in the tree.
 *
 * One handle, not two. The two panes divide all the space between them, so
 * dragging the line between them is both controls at once -- there is no third
 * state where one is shorter without the other being taller.
 */
function applySplit() {
	// Set on the element the two sections are children of, since that is what
	// their `flex-grow` reads them from. That was `#rail`; it is the left
	// panel now, and the two sections moved into it unchanged.
	const rail = $('#sidebar');
	if (!rail) return;
	// The panes are flex items with a basis of zero, so these two numbers are
	// simply the ratio they divide the free space in.
	rail.style.setProperty('--tree-share', String(Math.round(state.split * 1000)));
	rail.style.setProperty('--info-share', String(Math.round((1 - state.split) * 1000)));
	$('#rail-split')?.setAttribute('aria-valuenow', String(Math.round(state.split * 100)));
}

function setSplit(fraction, box) {
	// Clamped in pixels, not in fractions: a 15 per cent share is a usable
	// pane on a tall window and half a row on a short one.
	const room = box ?? $('#sidebar')?.getBoundingClientRect().height ?? 600;
	const min = Math.min(RAIL_MIN.tree / room, 0.45);
	const max = Math.max(1 - RAIL_MIN.info / room, 0.55);
	state.split = Math.max(min, Math.min(max, fraction));
	applySplit();
}

function wireRailSplit() {
	const bar = $('#rail-split');
	if (!bar || !$('#sidebar')) return;
	bar.setAttribute('aria-valuemin', '0');
	bar.setAttribute('aria-valuemax', '100');
	applySplit();

	/**
	 * What the two panes actually divide: their own heights, not the space
	 * between them. The handle and the gaps either side of it belong to
	 * neither, and counting them in made the pixel floor for each pane
	 * approximate.
	 */
	const measure = () => {
		const tree = $('#blocklist').getBoundingClientRect();
		const info = $('#info').getBoundingClientRect();
		return { tree: tree.height, room: tree.height + info.height };
	};

	// Taken as a delta from where the press landed, the way a node is dragged
	// on the diagram: the line then moves exactly as far as the pointer does,
	// which absolute positions do not manage -- a pane's padding and border
	// sit outside what flex divides, so the handle trailed the cursor by a few
	// pixels and the drag felt loose.
	let from = null;
	const move = (ev) => {
		if (!from) return;
		if (from.room > 0) {
			setSplit((from.tree + (ev.clientY - from.y)) / from.room, from.room);
		}
	};
	const stop = (ev) => {
		from = null;
		bar.classList.remove('is-dragging');
		document.body.classList.remove('is-splitting');
		if (bar.hasPointerCapture?.(ev.pointerId)) bar.releasePointerCapture(ev.pointerId);
	};
	bar.addEventListener('pointerdown', (ev) => {
		if (ev.button !== 0) return;
		from = { y: ev.clientY, ...measure() };
		bar.setPointerCapture(ev.pointerId);
		bar.classList.add('is-dragging');
		// The cursor has to stay a resize cursor over whatever it passes over,
		// or a drag that leaves the handle looks like it has been dropped.
		document.body.classList.add('is-splitting');
		ev.preventDefault();
	});
	bar.addEventListener('pointermove', move);
	bar.addEventListener('pointerup', stop);
	bar.addEventListener('pointercancel', stop);
	// Even shares again, which is the one arrangement nobody has to aim for.
	bar.addEventListener('dblclick', () => setSplit(0.56));
	bar.addEventListener('keydown', (ev) => {
		const { room } = measure();
		const step = (px) => { setSplit(state.split + px / room, room); ev.preventDefault(); };
		if (ev.key === 'ArrowUp') step(-16);
		else if (ev.key === 'ArrowDown') step(16);
		else if (ev.key === 'PageUp') step(-72);
		else if (ev.key === 'PageDown') step(72);
		else if (ev.key === 'Home') { setSplit(0); ev.preventDefault(); }
		else if (ev.key === 'End') { setSplit(1); ev.preventDefault(); }
	});
	// A window that has just become short must not leave one pane at nothing.
	// Skipped while the rail is folded away: there is then no height to
	// divide, and clamping a fraction against nothing would quietly move the
	// divider to the middle by the time the panel comes back.
	window.addEventListener('resize', () => {
		const { room } = measure();
		if (room > 0) setSplit(state.split, room);
	});
}

/**
 * The two side panels: how wide each is, and whether it is showing.
 *
 * Both are sized the same way and folded the same way, so both are driven from
 * one table (PANES) rather than from two near-copies. The width is a grid
 * track on `main` and `.work-body`; the panel itself has no width of its own,
 * which is what lets a folded panel take no room at all instead of leaving a
 * column behind.
 *
 * Widths are clamped here rather than in CSS, because the limit is not a
 * property of either panel on its own: what a panel may take is what is left
 * after the other panel and the middle have what they need. Re-applied on
 * every resize, so a window that has just become narrow squeezes the panels
 * instead of pushing the diagram off the edge -- which is what the `30vw` in
 * the CSS fallback does for the same reason.
 */
function paneLimits(side) {
	const room = $('main')?.getBoundingClientRect().width ?? 1200;
	// What the panels other than this one are holding. There are none now, and
	// this is written as a sum rather than as nothing so that a second panel
	// arriving does not need this read again.
	const taken = Object.keys(PANES)
		.filter((k) => k !== side && state.panes[k].shown)
		.reduce((n, k) => n + state.panes[k].width, 0);
	const min = PANES[side].min;
	// Each grip is six pixels and belongs to neither panel.
	return { min, max: Math.max(min, room - MIDDLE_MIN - taken - 6 * Object.keys(PANES).length) };
}

/**
 * The width a panel actually gets: what was asked for, within what there is
 * room for.
 *
 * The two are kept apart on purpose. `state.panes[side].width` is the width
 * someone chose and it is never written back to from here -- so a window that
 * has become too narrow squeezes the panel and a window that has become wide
 * again gives it the width it had, rather than leaving it at whatever the
 * narrow window forced. Squeezing it and calling that the new choice was the
 * first way this was written, and it quietly lost the setting.
 */
function paneWidth(side) {
	const pane = state.panes[side];
	if (!pane.shown) return 0;
	const { min, max } = paneLimits(side);
	return Math.round(Math.max(min, Math.min(max, pane.width)));
}

function applyPanes() {
	const app = $('#app') ?? document.body;
	for (const [side, spec] of Object.entries(PANES)) {
		const pane = state.panes[side];
		const { min, max } = paneLimits(side);
		const width = paneWidth(side);
		const applies = true;
		// Folded away it is nought wide *and* `hidden`: the width alone would
		// leave its contents laid out in a column of no width, which is a
		// column of overflow rather than a panel that is gone.
		app.style.setProperty(spec.width, `${width}px`);
		const panel = $(spec.panel);
		if (panel) panel.hidden = !pane.shown || !applies;

		const split = document.querySelector(`.pane-split[data-pane="${side}"]`);
		if (!split) continue;
		// On a tab the panel has nothing to say about, the grip goes too --
		// with its own column, or the middle would stop six pixels short of
		// the window for a divider with nothing on the other side of it.
		split.hidden = !applies;
		if (spec.gap) app.style.setProperty(spec.gap, applies ? '6px' : '0px');
		split.classList.toggle('is-collapsed', !pane.shown);
		const grip = split.querySelector('.pane-grip');
		if (grip) {
			grip.setAttribute('aria-valuemin', String(min));
			grip.setAttribute('aria-valuemax', String(max));
			grip.setAttribute('aria-valuenow', String(width));
		}
		const toggle = split.querySelector('.pane-toggle');
		if (toggle) {
			toggle.textContent = pane.shown ? spec.fold : spec.unfold;
			toggle.setAttribute('aria-expanded', String(pane.shown));
			const what = `${pane.shown ? 'Hide' : 'Show'} the ${spec.name}`;
			toggle.title = what;
			toggle.setAttribute('aria-label', what);
		}
	}
}

/**
 * A width someone chose, which is a new wish rather than a passing squeeze --
 * so it is clamped as it is stored. Without that, dragging past the far edge
 * would bank a width off the screen and the panel would sit still for the
 * first hundred pixels of the drag back.
 */
/**
 * Brings a panel back if it has been folded away.
 *
 * Called before anything puts the caret in a field inside one: focus on a
 * hidden element does nothing at all, so without this, clicking the model's
 * name in the header while the left panel was folded would look like a dead
 * control -- which is exactly the fault the model card's `Edit...` had.
 */
function revealPane(side) {
	if (state.panes[side].shown) return;
	showPane(side, true);
}

function setPaneWidth(side, px) {
	const { min, max } = paneLimits(side);
	state.panes[side].width = Math.round(Math.max(min, Math.min(max, px)));
	applyPanes();
}

/**
 * Folds a panel away, or brings it back.
 *
 * Nothing has to be redrawn here. The diagram and the chart both watch their
 * own container with a ResizeObserver, and what folding a side panel changes
 * is exactly that container's width -- measured: the chart's canvas went from
 * 314 pixels to 624 on its own when the rail was folded.
 */
function showPane(side, on) {
	state.panes[side].shown = on;
	applyPanes();
}

function wirePaneSplits() {
	for (const [side, spec] of Object.entries(PANES)) {
		const split = document.querySelector(`.pane-split[data-pane="${side}"]`);
		const grip = split?.querySelector('.pane-grip');
		const toggle = split?.querySelector('.pane-toggle');
		if (!grip) continue;

		// Which way widens it: dragging right gives the left panel more and
		// the right panel less.
		const sign = side === 'left' ? 1 : -1;
		// A delta from where the press landed, as on the rail's divider and on
		// the diagram: the line then moves exactly as far as the pointer does,
		// whatever padding and borders sit between them.
		let from = null;
		const move = (ev) => {
			if (from) setPaneWidth(side, from.width + sign * (ev.clientX - from.x));
		};
		const stop = (ev) => {
			from = null;
			grip.classList.remove('is-dragging');
			document.body.classList.remove('is-splitting-x');
			if (grip.hasPointerCapture?.(ev.pointerId)) grip.releasePointerCapture(ev.pointerId);
		};
		grip.addEventListener('pointerdown', (ev) => {
			// A folded panel has no width to drag. The chevron is the way back.
			if (ev.button !== 0 || !state.panes[side].shown) return;
			from = { x: ev.clientX, width: state.panes[side].width };
			grip.setPointerCapture(ev.pointerId);
			grip.classList.add('is-dragging');
			document.body.classList.add('is-splitting-x');
			ev.preventDefault();
		});
		grip.addEventListener('pointermove', move);
		grip.addEventListener('pointerup', stop);
		grip.addEventListener('pointercancel', stop);
		// Its usual width again -- and back on screen if it was folded away,
		// since a double-click on the grip of a panel that is not there can
		// only mean one thing.
		grip.addEventListener('dblclick', () => {
			state.panes[side].shown = true;
			setPaneWidth(side, spec.def);
		});
		grip.addEventListener('keydown', (ev) => {
			const step = (px) => { setPaneWidth(side, state.panes[side].width + px); ev.preventDefault(); };
			const { min, max } = paneLimits(side);
			if (ev.key === 'ArrowLeft') step(sign * -16);
			else if (ev.key === 'ArrowRight') step(sign * 16);
			else if (ev.key === 'PageUp') step(sign * -72);
			else if (ev.key === 'PageDown') step(sign * 72);
			else if (ev.key === 'Home') { setPaneWidth(side, min); ev.preventDefault(); }
			else if (ev.key === 'End') { setPaneWidth(side, max); ev.preventDefault(); }
		});
		toggle?.addEventListener('click', () => showPane(side, !state.panes[side].shown));
	}
	applyPanes();
	// A window that has just become narrow squeezes the panels rather than the
	// middle, and one that has become wide lets them have what they asked for
	// back again.
	window.addEventListener('resize', applyPanes);
}

/**
 * The right-hand rail: the tree of the model, and what the selected block is.
 *
 * There used to be a third thing above both -- a property form for the
 * selection, holding the name and the one or two fields that say what the
 * block *is*. It is gone. In a 310-pixel column it was a third editor of the
 * same block (the left panel and the settings dialog being the other two), and
 * the two halves anyone actually navigates by, the tree and the Information
 * view, were left sharing whatever was underneath it. Editing now happens in
 * the dialog, which is where everything a block can carry already lived.
 */
/**
 * The Information view, on its own.
 *
 * Separate from the rest of the rail because it is the one card that can
 * change without an edit: what the equations come to at the start is worked
 * out a moment after the edit that changed them, and the rows behind a block
 * -- one per index -- have to be built from that answer rather than written
 * into a line that is already on screen. Nothing in this card takes typing,
 * so building it again is free of the hazard that keeps the settings dialog
 * from being rebuilt when the values arrive.
 */
function renderInfoCard() {
	// Out in its window again if it was when this browser last had the page:
	// once, with the first model on screen, since the window shows one.
	if (!infoRestored && state.raw) {
		infoRestored = true;
		if (readInfoWindow()?.out && !infoWin) { popInfo(); return; }
	}
	// With nothing selected while the diagram is inside a sub-system, the
	// view reads that sub-system: it is what is in front of you, and the
	// whole model is one click up. `implied` lets the view say so, and offer
	// the way up rather than a way in.
	const here = graph?.currentSystem ?? '';
	const shown = state.selection
		?? (here && ed.systems(state.raw).includes(here)
			? { kind: 'system', name: here, implied: true }
			: null);
	// In its window, when it is out (`popInfo`): the window's body, and its
	// buttons in the window's title bar. An edit rebuilds the view, so the
	// place it was scrolled to is kept while it goes on showing the same
	// thing -- a window read halfway down a block's equations should not jump
	// to the top at every keystroke.
	const win = infoWin?.body ? infoWin : null;
	const key = shown ? `${shown.kind}:${shown.name}` : '';
	const top = win && win.shown === key ? win.body.scrollTop : 0;
	renderInfo(win ? win.body : $('#info'), state.raw, shown, {
		atStart: startValueFor,
		marks: state.marks,
		// Scanned once per edit by `rescanProblems`; the card reads that
		// rather than walking the model again for the same answer.
		unitProblems: state.unitProblems,
		onSelect: setSelection,
		onOpenSystem: (path) => { graph?.setSystem(path); selectTab('build'); },
		onOpenSettings: openBlockSettings,
		onOpenIndexList: openIndexLists,
		// Double-clicking the model's name puts the caret in the field that
		// spells it, which is what clicking the name in the window header
		// already does. There is no dialog to open: the model's own settings
		// are the left panel, and it is never hidden.
		onEditName: () => {
			revealPane('left');
			openSection('model');
			$('#sidebar [data-section="model"]')?.scrollIntoView({ block: 'nearest' });
			$('#model-name')?.focus();
		},
		onContextMenu: blockMenu,
		onBack: () => stepTrail(-1),
		onForward: () => stepTrail(1),
		info: win ? null : () => infoButton('panel:information', () => panelTopic('information')),
		bar: win ? win.bar : null,
		onPopOut: win ? null : () => popInfo(),
		canBack: state.trail.at > 0,
		canForward: state.trail.at >= 0 && state.trail.at < state.trail.seen.length - 1,
	});
	if (win) {
		win.body.scrollTop = top;
		win.shown = key;
	}
}

/**
 * The Information view in a window of its own, for as long as it is out.
 *
 * A floating window like a block's settings (see `openModal`): moved by its
 * title bar, sized by its corner, in front when pressed, and the page usable
 * around it -- so it can sit over the canvas, or beside it on a second screen's
 * worth of window, while the tree has the whole of the rail. Kept open when
 * another model is opened, because it shows whatever model is in front of it.
 * Its × or Escape puts the view back in the rail.
 *
 * Where it was, how big, and whether it was out are remembered in this
 * browser (`kompartment.infoWindow`), as a convenience and nothing more:
 * without storage it opens beside the rail every time.
 */
const INFO_WINDOW_KEY = 'kompartment.infoWindow';
let infoWin = null;
let infoRestored = false;

function readInfoWindow() {
	try {
		const v = JSON.parse(localStorage.getItem(INFO_WINDOW_KEY) ?? 'null');
		return v && typeof v === 'object' ? v : null;
	} catch { return null; }
}

function writeInfoWindow(v) {
	try { localStorage.setItem(INFO_WINDOW_KEY, JSON.stringify(v)); } catch { /* not kept: fine */ }
}

function popInfo() {
	if (infoWin) { infoWin.handle?.focus(); return; }
	const bar = el('div', { className: 'info-window-bar' });
	const win = { bar, body: null, handle: null, shown: null };
	infoWin = win;
	$('#sidebar')?.classList.add('is-info-out');
	$('#info')?.replaceChildren();
	const handle = openModal({
		// The view's own topic, as its (i) in the rail has it.
		info: { key: 'panel:information', topic: () => panelTopic('information') },
		title: 'Information',
		floating: true,
		keep: true,
		className: 'is-info-window',
		build: (body) => { win.body = body; renderInfoCard(); },
		onClose: () => {
			writeInfoWindow({ ...boxOf(handle), out: false });
			if (infoWin === win) infoWin = null;
			$('#sidebar')?.classList.remove('is-info-out');
			renderInfoCard();
		},
	});
	win.handle = handle;
	// The view's own buttons in the window's title bar, before its (i): where
	// they are in the rail.
	handle.head.insertBefore(bar, handle.head.querySelector('.info-btn') ?? handle.head.lastChild);
	// Its close button puts the view back rather than closing anything, so
	// it shows that: the pop-out button's box, with the arrow coming home.
	const back = handle.dialog.querySelector('.modal-close');
	back.classList.add('is-pop-back');
	back.replaceChildren(popIcon('back'));
	back.title = 'Put Information back in the panel (Esc)';
	back.setAttribute('aria-label', 'Put Information back in the panel');

	// Where it was last, kept on the screen; the first time, beside the rail.
	const saved = readInfoWindow();
	const rail = $('#sidebar')?.getBoundingClientRect();
	const w = Math.round(Math.min(window.innerWidth - 16, Math.max(320, saved?.width ?? 400)));
	const h = Math.round(Math.min(window.innerHeight - 120, Math.max(120, saved?.height ?? window.innerHeight * 0.6)));
	handle.dialog.style.width = `${w}px`;
	handle.dialog.style.maxHeight = 'none';
	handle.body.style.height = `${h}px`;
	handle.body.style.maxHeight = `${h}px`;
	const x = saved?.left ?? (rail ? rail.right + 16 : 40);
	const y = saved?.top ?? (rail ? rail.top + 8 : 80);
	handle.dialog.style.left = `${Math.round(Math.min(window.innerWidth - 80, Math.max(0, x)))}px`;
	handle.dialog.style.top = `${Math.round(Math.min(window.innerHeight - 60, Math.max(0, y)))}px`;
	// Kept as it is left after every move and resize, so a reload finds it
	// where it was even if it was never closed.
	handle.dialog.addEventListener('pointerup', () => writeInfoWindow({ ...boxOf(handle), out: true }));
	writeInfoWindow({ ...boxOf(handle), out: true });
}

/** A window's place and size, as `popInfo` puts them back. */
function boxOf(handle) {
	const r = handle.dialog.getBoundingClientRect();
	const b = handle.body.getBoundingClientRect();
	return r.width > 0
		? { left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(b.height) }
		: { ...(readInfoWindow() ?? {}) };
}

function renderRail({ tree = true } = {}) {
	// A selection of several is otherwise visible only as highlighting on the
	// diagram, and the number is what you want to know before pressing Del.
	// It says which of them Information is describing, because that panel
	// reads one block while the selection is many.
	const picked = $('#picked');
	picked.replaceChildren();
	picked.hidden = state.picked.length <= 1;
	if (!picked.hidden) {
		const paths = ed.systems(state.raw);
		const subs = state.picked.filter((n) => paths.includes(n)).length;
		const blocks = state.picked.length - subs;
		const bits = [];
		if (blocks) bits.push(blocks === 1 ? '1 block' : `${blocks} blocks`);
		if (subs) bits.push(subs === 1 ? '1 sub-system' : `${subs} sub-systems`);
		const line = el('div', { className: 'picked-line' },
			el('b', {}, `${bits.join(' and ')} selected`));
		// A selection made in the tree reaches across sub-systems, and the
		// canvas shows one of them at a time. Without this the ones that are
		// somewhere else are selected and invisible, which reads as a
		// selection that did not take.
		const here = graph?.currentSystem ?? '';
		const away = state.picked.filter((n) => parentOf(n) !== here).length;
		if (away) {
			line.append(el('span', {
				title: 'The diagram shows one sub-system at a time. They are still '
					+ 'selected, and Cut, Copy and Delete act on all of them.',
			}, `${away} elsewhere`));
		}
		if (state.selection?.name) {
			line.append(el('span', {}, `showing ${state.selection.name}`));
		}
		const clear = el('button', {
			className: 'ghost', type: 'button', title: 'Escape does this too',
		}, 'Clear');
		clear.addEventListener('click', () => setSelection(null, []));
		line.append(clear);
		picked.append(line);
	}
	renderInfoCard();
	renderSearch();
	// Skipped where the edit cannot have changed a block: the tree is a row
	// per block and rebuilding it is the largest thing an edit does.
	if (!tree) { applySearchToGraph(); return; }
	renderBlockTree($('#blocklist'), state.raw, state.selection, {
		onSelect: setSelection,
		marks: state.marks,
		// What the sample on screen holds, so the tree can say which blocks a
		// chart of them will draw as a spread: the endpoints the run kept and
		// the parameters it varied.
		sample: sampleHolds()?.blocks ?? null,
		onOpenSystem: (path) => { graph?.setSystem(path); selectTab('build'); },
		currentSystem: graph?.currentSystem ?? '',
		picked: state.picked,
		onOpenSettings: openBlockSettings,
		onContextMenu: blockMenu,
		// The empty space below the rows: a place, not a thing. The top level,
		// since that is what the tree as a whole is a view of.
		onPlaceMenu: (system, ev) => graph?.openPasteMenu(system, ev.clientX, ev.clientY),
		onMoveTo: (names, system) => graph?.moveInto(names, system),
		onDelete: () => graph?.deleteSelected(),
	}, treeFilter(), state.tree);
	applySearchToGraph();
}

/**
 * The blocks the buttons beside the search make.
 *
 * Three, not thirteen: a compartment, an expression and a parameter are what a
 * model is mostly made of, and the rest are a right-click away on the canvas
 * where they can be put somewhere on purpose.
 */
const QUICK_ADD = [
	{ kind: 'compartment', what: 'Add a compartment',
		make: (raw, system) => ed.addCompartment(raw, { system }) },
	{ kind: 'expression', what: 'Add an expression',
		make: (raw, system) => ed.addExpression(raw, { system }) },
	{ kind: 'parameter', what: 'Add a parameter',
		make: (raw, system) => ed.addParameter(raw, { system }) },
];

/**
 * The three Add buttons, as tabs on the top edge of the tree.
 *
 * On the row with the kind chips they were three more controls in a line that
 * already had four, and they read as filters because everything beside them
 * was one. Here they are against the thing they add to, and they are the only
 * controls in the row -- so the row itself says what they do.
 *
 * The block's own icon rather than a letter: a compartment is the rounded box
 * the diagram draws, an expression that box with an equals sign in it, a
 * parameter a hexagon, and those are the shapes already on the canvas and in
 * the tree below. `C+` had to be learned; this is the thing itself.
 *
 * The icon alone, with no `+` on it: `Add` at the head of the row says what the
 * three do, and saying it again on each of them is the same word three times
 * across 90 pixels.
 */
function addTabs() {
	const row = el('div', { className: 'tree-tabs' });
	// Expand all and Collapse at the left, where the row has room: between
	// this row and the tree they parted the tabs from the edge they stand on.
	const tools = treeTools(state.raw, state.tree, () => renderRail(), treeFilter());
	if (tools) row.append(tools);
	row.append(el('span', { className: 'tree-tabs-what' }, 'Add'));
	for (const spec of QUICK_ADD) {
		const add = el('button', {
			className: 'tree-tab', type: 'button',
			'aria-label': spec.what,
			title: `${spec.what} — added to whichever sub-system the diagram is `
				+ 'showing, and selected so the settings are one click away',
		}, blockIcon(spec.kind));
		add.dataset.chip = `add:${spec.kind}`;
		add.addEventListener('click', () => quickAdd(spec));
		row.append(add);
	}
	return row;
}

/**
 * Makes one, in the sub-system the diagram is showing.
 *
 * Read now rather than when the panel was drawn: going into a sub-system does
 * not redraw this panel, so a system captured at render time would be the one
 * you had left. The same trap the old per-section `+` buttons had.
 */
function quickAdd(spec) {
	try {
		const system = graph?.currentSystem ?? '';
		const made = spec.make(state.raw, system);
		const qname = ed.qualifiedName(made);
		state.selection = { kind: spec.kind, name: qname };
		state.picked = [qname];
		modelChanged();
		// Where it went is worth saying when it is not the top level: the panel
		// lists every sub-system's blocks together, and a new one in a
		// sub-system you are not looking at is otherwise added silently.
		flash(system ? `Added ${qname} in ${system}.` : `Added ${qname}.`, 'info');
		// ...and, with the diagram in view, whether it is drawn there. A
		// parameter added while `Show ▸ parameters` is off lands on a canvas
		// that does not change, which reads as a click that did not take. Not
		// said from any other tab: it is about a diagram nobody is looking at.
		if (state.tab === 'build') graph?.sayIfNotDrawn(qname);
	} catch (e) {
		flash(e.message, 'warn');
	}
}

/** Whether the thirteen kind chips are showing. Remembered for the session. */
let kindsOpen = false;

/**
 * The block search: a name box, and the kind filter behind a disclosure.
 *
 * The filter is thirteen chips, which in a 310-pixel column is four wrapped
 * rows -- so above a tree that is now the main thing in the panel, the search
 * took more room than the first screenful of what it searches. Closed it is
 * one line that says what is filtered; opened it is the same cloud of chips it
 * always was. The count of matches shares that line rather than having one of
 * its own.
 *
 * Rebuilt on every rail render like everything else, so the query lives in
 * `state`; the input is only re-created when it does not hold the caret, since
 * typing here re-renders the list under it on every keystroke.
 */
/**
 * Remembering which control in a rebuilt widget had the keyboard.
 *
 * The group and the value are two attributes rather than one joined key,
 * because `CSS.escape` turns a NUL into U+FFFD -- so a selector built from a
 * NUL-joined key matches nothing, silently, and the focus is lost exactly as
 * it was before. Two attributes need no separator at all.
 */
const chipKey = (el) => (el?.dataset?.chip
	? { chip: el.dataset.chip, value: el.dataset.chipvalue ?? '' }
	: null);

const focusChip = (host, key) => {
	if (!key) return;
	for (const el of host.querySelectorAll('[data-chip]')) {
		if (el.dataset.chip === key.chip && (el.dataset.chipvalue ?? '') === key.value) {
			el.focus();
			return;
		}
	}
};

/**
 * Opens the question dialog, and pins what it answers.
 *
 * The model handed over is the one the editor holds, which has been through
 * `materialiseShorthand` -- so a parameter written as `values_by_nuclide`
 * carries the radionuclide dimension the same way one written out longhand
 * does, and *Indexed over* finds both.
 */
function openQuery() {
	openQueryDialog({
		project: state.raw,
		blocks: ed.blockNames(state.raw).sort((a, b) => a.localeCompare(b)),
		lists: (state.raw.index_lists ?? []).map((l) => l.name ?? String(l)).filter(Boolean),
		systems: ed.systems(state.raw),
		selected: state.selection?.name ?? '',
		onPin: (found, label) => {
			state.search.only = found;
			state.search.onlyLabel = label;
			// A pinned answer with the old name filter still in the box shows
			// nothing and looks broken, so the box is cleared: the question is
			// the filter now.
			state.search.query = '';
			renderRail();
			renderSearch();
			flash(`${found.length.toLocaleString()} block${found.length === 1 ? '' : 's'}: `
				+ `${label}.`, 'info');
		},
	});
}

function clearQuery() {
	state.search.only = null;
	state.search.onlyLabel = '';
	renderRail();
	renderSearch();
}

function renderSearch() {
	const host = $('#search');
	const active = document.activeElement;
	const keepInput = active && active.id === 'search-name' && host.contains(active);
	const caret = keepInput ? [active.selectionStart, active.selectionEnd] : null;
	// Which control had the keyboard, if it was not the box. Everything in
	// here is destroyed and rebuilt on each render, so clicking a kind chip
	// moved the focus to the body and the next Tab started again from the top
	// of the page -- in the middle of narrowing a list of a thousand blocks
	// down to the four you were looking for.
	const focused = !keepInput && active && host.contains(active) ? chipKey(active) : null;

	host.replaceChildren();

	const input = el('input', {
		type: 'search', id: 'search-name', className: 'search-input',
		value: state.search.query, spellcheck: false,
		placeholder: 'Find a block — try C*_out',
		title: 'Matches anywhere in the name. With * or ? it is a pattern over '
			+ 'the whole name: * any run of characters, ? exactly one.',
	});
	// Filtering as you type is the point of it, so this is one of the few
	// places that listens to `input` rather than `change`.
	input.addEventListener('input', () => {
		state.search.query = input.value;
		renderRail();
	});
	input.addEventListener('keydown', (e) => {
		if (e.key === 'Escape') {
			state.search.query = '';
			state.search.kinds.clear();
			renderRail();
		}
	});
	// The tree's (i), to the right of the search box as every other (i) is to
	// the right of its field: what the search, the filters, the Add tabs and
	// the rows below can do. See ./panelinfo.js.
	host.append(el('div', { className: 'search-row' }, input,
		infoButton('panel:tree', () => panelTopic('tree', {
			systems: ed.systems(state.raw).length > 0,
			sample: !!sampleHolds(),
		}))));

	// One line: what the filter is set to, and how much it leaves.
	const total = ed.allBlocks(state.raw).length;
	const filter = treeFilter();
	const shown = ed.searchBlocks(state.raw, filter).length;
	const chosen = state.search.kinds.size;
	const filtering = !!state.search.query.trim() || chosen > 0 || !!filter.only;
	const held = sampleHolds();

	const line = el('div', { className: 'search-line' });

	// How the list below is arranged, beside what is in it. This was a button
	// in the tree's own bar; the two say the same kind of thing -- one narrows
	// the list, the other arranges it -- and they read as a pair.
	const group = el('button', {
		className: `search-chip${state.tree.group ? ' is-on' : ''}`,
		type: 'button',
		'aria-pressed': state.tree.group ? 'true' : 'false',
		title: 'Put the blocks of each sub-system under a heading per kind. '
			+ 'Worth having when one sub-system holds hundreds of them.',
	}, 'Group by type');
	group.dataset.chip = 'group';
	group.addEventListener('click', () => { state.tree.group = !state.tree.group; renderRail(); });
	line.append(group);

	// The questions a name cannot answer. Beside the kind chips because it is
	// the same kind of control -- both narrow what the tree shows -- and one
	// character wide because the panel is 306 pixels and the other five
	// controls were there first.
	const ask = el('button', {
		className: `search-chip${state.search.only ? ' is-on' : ''}`,
		type: 'button',
		title: 'Ask the model a question: what reads this block, what it needs, '
			+ 'what nothing reads, which blocks are only data. The answer is '
			+ 'shown in this panel.',
	}, '?');
	ask.dataset.chip = 'ask';
	ask.addEventListener('click', () => openQuery());
	line.append(ask);

	// Only what the sample holds: the endpoints the probabilistic run kept and
	// the parameters it varied, which the tree marks. There while a sample is
	// on screen and gone with it, when it would be a filter for nothing.
	if (held) {
		const on = !!state.search.sample;
		const only = el('button', {
			className: `search-chip search-chip-sample${on ? ' is-on' : ''}`,
			type: 'button',
			'aria-pressed': on ? 'true' : 'false',
			title: `Show only the ${held.blocks.size.toLocaleString()} blocks the probabilistic `
				+ 'run has realisations of: the endpoints it kept and the parameters it varied.',
		}, sampleMark('kept'), 'Probabilistic');
		only.dataset.chip = 'sample';
		only.addEventListener('click', () => {
			state.search.sample = !on;
			renderRail();
		});
		line.append(only);
	}

	const toggle = el('button', {
		className: `search-toggle${kindsOpen ? ' is-open' : ''}`,
		type: 'button',
		'aria-expanded': kindsOpen ? 'true' : 'false',
		title: 'Limit the search to particular kinds of block',
	},
	el('span', { className: 'search-caret', 'aria-hidden': 'true' }, kindsOpen ? '▾' : '▸'),
	el('span', {}, chosen === 0
		? 'All kinds'
		: chosen === 1
			? ed.KIND_LABEL[[...state.search.kinds][0]]
			: `${chosen} kinds`));
	toggle.dataset.chip = 'toggle';
	toggle.addEventListener('click', () => { kindsOpen = !kindsOpen; renderSearch(); });
	line.append(toggle);

	if (filtering) {
		line.append(el('span', { className: 'search-status' }, shown === 0
			? 'no match'
			: `${shown} of ${total}`));
		const clear = el('button', {
			className: 'ghost search-clear', type: 'button',
			title: 'Escape in the box above does this too',
		}, 'Clear');
		clear.addEventListener('click', () => {
			state.search.query = '';
			state.search.kinds.clear();
			state.search.only = null;
			state.search.onlyLabel = '';
			state.search.sample = false;
			renderRail();
			renderSearch();
		});
		line.append(clear);
	}

	// What the pinned answer *was*, because a set of names is not
	// self-describing: "13 of 4,500" says nothing about which thirteen.
	if (state.search.only) {
		host.append(el('div', { className: 'search-pin' },
			el('span', { className: 'search-pin-what' }, state.search.onlyLabel),
			(() => {
				const off = el('button', {
					className: 'ghost search-pin-off', type: 'button',
					title: 'Stop showing only these',
				}, '×');
				off.addEventListener('click', clearQuery);
				return off;
			})()));
	}
	host.append(line);

	if (!kindsOpen) {
		host.append(addTabs());
		if (keepInput) {
			input.focus();
			if (caret) input.setSelectionRange(caret[0], caret[1]);
		} else {
			focusChip(host, focused);
		}
		return;
	}

	const chips = el('div', { className: 'search-kinds' });
	for (const kind of ed.SEARCH_KINDS) {
		const on = state.search.kinds.has(kind);
		// By the collection each kind lives in, not by adding an `s`: the
		// plural of `min_max` is `min_maxes`, and a chip for a kind the model
		// does have would otherwise be greyed out.
		const count = (state.raw[ed.PLURAL[kind]] ?? []).length;
		const chip = el('button', {
			className: `search-chip${on ? ' is-on' : ''}`,
			type: 'button',
			disabled: count === 0,
			title: count
				? `${ed.KIND_LABEL[kind]} (${count})`
				: `No ${ed.KIND_LABEL[kind].toLowerCase()} in this model`,
		}, ed.KIND_LABEL[kind]);
		chip.dataset.chip = 'kind';
		chip.dataset.chipvalue = kind;
		chip.addEventListener('click', () => {
			// No kind ticked means every kind, so ticking the last one off
			// returns to showing everything rather than nothing.
			if (on) state.search.kinds.delete(kind);
			else state.search.kinds.add(kind);
			renderRail();
		});
		chips.append(chip);
	}
	host.append(chips);
	host.append(addTabs());

	if (keepInput) {
		input.focus();
		if (caret) input.setSelectionRange(caret[0], caret[1]);
	} else {
		focusChip(host, focused);
	}
}

/**
 * The block clipboard.
 *
 * Its own thing rather than the system clipboard: what is copied here is a set
 * of blocks with their equations, their per-index values and the connections
 * between them, and there is no text form of that worth pasting into a text
 * editor. It survives loading another model, so a block can be carried from
 * one to the other -- the one thing a single-tab editor cannot do any other
 * way -- and `pasteBlocks` drops any index list the receiving model has never
 * heard of rather than leaving it unbuildable.
 */
/**
 * Takes a copy of what is selected -- blocks, sub-systems or both.
 *
 * The clipboard is the application's, not the diagram's: the block tree opens
 * the same menus, and two clipboards that disagreed about what had been copied
 * would be worse than one that is sometimes empty.
 */
function copySelection(names) {
	try {
		const payload = ed.copySelection(state.raw, names);
		// The two answer the same Paste, so asking for one calls the other off.
		clearPendingCut();
		state.clipboard = payload;
		state.clipboardAt = Date.now();
		// And to the other tabs of this origin, so a copy here is a paste in
		// the window beside it. The in-page copy above is the real one: this
		// can decline -- storage switched off, or a copy larger than a share
		// of the quota -- and a copy that is not shared still pastes here.
		const out = shared.put(payload, { model: ed.modelName(state.raw) });
		if (out.ok) state.clipboardAt = out.at;
		const info = clipboardInfo();
		const inside = payload.blocks.filter((b) => b.part >= 0).length;
		// What came along without being asked for: the arrows between the
		// blocks in the copy.
		const asked = new Set(names);
		const extra = payload.blocks.filter((b) => b.part < 0 && !asked.has(b.name)).length;
		const left = payload.stranded?.length ?? 0;
		flash(
			`Copied ${info.what}`
			+ (inside ? `, with the ${inside} block${inside === 1 ? '' : 's'} inside` : '')
			+ (extra > 0
				? `, including the ${extra} connection${extra === 1 ? '' : 's'} between them`
				: '')
			+ (left
				? `. ${left} connection${left === 1 ? '' : 's'} will stay behind: `
					+ (info.whole
						? `${left === 1 ? 'it leaves' : 'they leave'} ${info.what}`
						: `only one end is in the copy`)
				: '')
			+ '. Right-click the canvas to paste'
			+ (out.ok ? ', here or in another tab' : '')
			+ '.'
			// Only when it was worth sharing and could not be: a browser that
			// holds nothing at all is not a thing to report on every copy.
			+ (!out.ok && shared.available()
				? ` It is ${out.why}, so another tab of this model will not see it.`
				: ''),
			'info',
		);
	} catch (e) {
		flash(e.message, 'warn');
	}
}
/**
 * Marks what is selected to be moved, and changes nothing yet.
 *
 * Not copy-and-delete. A cut here is a *pending move*: the blocks stay exactly
 * where they are, marked on the diagram, until a Paste says where they should
 * go -- and then they move, rather than a copy appearing and the original
 * being destroyed. Nothing is deleted at any point, so a cut that is never
 * pasted has cost nothing and there is nothing to undo.
 *
 * It lasts until the next edit. Anything that changes the model -- including
 * an undo, and including loading another model -- takes the mark off and
 * leaves the blocks alone, because a move whose source has been edited under
 * it is a move nobody asked for. Navigating is not editing: going into a
 * sub-system to paste there is the whole point.
 */
function cutSelection(names) {
	if (!names?.length) return;
	// A cut and a copy answer the same Paste, so the second one to be asked
	// for is the one that is pending.
	state.clipboard = null;
	state.pendingCut = { names: [...names], system: graph?.currentSystem ?? '' };
	graph?.setPendingCut(state.pendingCut.names);
	const what = names.length === 1 ? names[0] : `${names.length} blocks`;
	flash(`${what} ready to move. Right-click where ${names.length === 1 ? 'it' : 'they'} `
		+ 'should go and choose Paste — nothing has changed yet, and any other edit '
		+ 'calls it off.', 'info');
}

/**
 * Takes the mark off, wherever the cut was called off from.
 *
 * Called by every edit. The paste clears it itself before it moves anything,
 * so the move it performs does not cancel the move it is performing.
 */
function clearPendingCut() {
	if (!state.pendingCut) return;
	state.pendingCut = null;
	graph?.setPendingCut(null);
}

function pasteClipboard({ system = null, at = null } = {}) {
	// A cut is pending: this is a move, not a copy, and the blocks that move
	// are the ones that were marked -- not a duplicate of them.
	if (state.pendingCut) {
		const { names } = state.pendingCut;
		// Cleared before the move and not after: the move is an edit, every
		// edit calls a pending cut off, and a paste that cancelled itself
		// halfway would be a paste that half happened.
		clearPendingCut();
		graph?.movePendingCut(names, system ?? '', at);
		return;
	}
	const what = clipboardNow();
	if (!what) { flash('Nothing has been cut or copied yet.', 'warn'); return; }
	try {
		arrived('Pasted', ed.pasteBlocks(state.raw, what.payload, { system, at }));
		// Where it came from, when it came from somewhere else. A paste that
		// silently produced another tab's blocks would be the wrong kind of
		// surprise, and the model it was taken from is the one fact that makes
		// it obvious what happened.
		if (what.from) {
			flash(`Pasted from ${what.from}, copied in another tab.`, 'info');
		}
	} catch (e) {
		flash(e.message, 'warn');
	}
}

/**
 * The clipboard as it stands, this tab's and every other tab's together.
 *
 * The last thing copied anywhere is the thing that pastes, which is what a
 * clipboard means -- so the two are compared by when they were taken. This
 * tab's own is preferred on a tie, since that is the copy that is certainly
 * intact: the shared one is a round-trip through JSON and could have been
 * written by a version of this application that is not the one running.
 *
 * @returns {{payload: object, from: string|null}|null} `from` names the model
 *   the copy came out of when it came from another tab, and is null when it is
 *   this tab's own.
 */
function clipboardNow() {
	const mine = state.clipboard
		? { payload: state.clipboard, at: state.clipboardAt, from: null }
		: null;
	const rec = shared.get();
	if (!rec) return mine;
	if (mine && mine.at >= rec.at) return mine;
	return { payload: rec.payload, from: rec.meta?.model || 'another model' };
}

/** The new sub-systems a paste made, and the blocks that are not inside one. */
function landed(r) {
	const systems = r.systems ?? (r.system ? [r.system] : []);
	return { systems, own: r.added.filter((n) => !systems.some((p) => isWithin(n, p))) };
}

function arrived(verb, r) {
	modelChanged();
	// A sub-system is selected as itself rather than by its contents: it is
	// not a block, so nothing in it is the thing that arrived. That brings up
	// the canvas it landed *on*, with the new node on it, which is what you
	// want to see -- a clone beside its original, or a paste in the sub-system
	// you aimed it at. Double-click to go in.
	const { systems, own } = landed(r);
	const picked = [...systems, ...own];
	const head = picked[0] ?? null;
	if (head) {
		setSelection({
			kind: systems.includes(head) ? 'system' : ed.findBlock(state.raw, head)?.kind,
			name: head,
		}, picked);
	}
	flash(pasteReport(verb, r), 'info');
}
function pasteReport(verb, r) {
	const { systems, own } = landed(r);
	const deep = r.added.length - own.length;
	const home = own.length ? (ed.findBlock(state.raw, own[0])?.block.system ?? '') : '';
	const bits = [];
	if (own.length) bits.push(own.length === 1 ? own[0] : `${own.length} blocks`);
	if (systems.length) {
		bits.push(systems.length === 1 ? systems[0] : `${systems.length} sub-systems`);
	}
	const whole = systems.length && !own.length;
	return `${verb} ${bits.join(' and ') || 'nothing'}`
		+ (deep ? `, with the ${deep} block${deep === 1 ? '' : 's'} in `
			+ `${systems.length === 1 ? 'it' : 'them'}` : '')
		+ (own.length && home ? ` into ${home}` : '')
		+ (r.renamed.length === 1
			? `. ${baseName(r.renamed[0][0])} became ${baseName(r.renamed[0][1])}, `
				+ 'that name being taken'
			: r.renamed.length
				? `. ${r.renamed.length} were renamed, those names being taken`
				: '')
		+ (r.stranded?.length
			? `. ${r.stranded.length} connection${r.stranded.length === 1 ? '' : 's'} `
				+ 'stayed behind: '
				+ (whole
					? `${r.stranded.length === 1 ? 'it leaves' : 'they leave'} the sub-system`
					: 'only one end was selected')
			: '')
		+ (r.dropped?.length
			? `. Dropped the index list${r.dropped.length === 1 ? '' : 's'} `
				+ `${r.dropped.join(', ')}, which this model does not have`
			: '')
		+ (r.shadowed?.length
			? `. ${r.shadowed[0].block} reads '${r.shadowed[0].reference}', which in `
				+ `${r.shadowed[0].where} means a different block`
				+ (r.shadowed.length > 1 ? ` (${r.shadowed.length - 1} more)` : '')
				+ ' — check it'
			: '')
		+ (r.lostEntries
			? `${r.dropped?.length ? ', and' : '. Dropped'} ${r.lostEntries} `
				+ `per-index value${r.lostEntries === 1 ? '' : 's'} keyed on `
				+ 'an index it does not have'
			: '')
		+ '.';
}

/**
 * What the clipboard holds, for the menu items that offer to paste it.
 *
 * `whole` is the one case worth wording differently: a single sub-system, on
 * its own, whose copy is everything inside it.
 */
function clipboardInfo() {
	// The clipboard as it stands, not this tab's alone: the Paste item asks
	// this whether there is anything to paste, and a copy taken in the window
	// beside this one is something to paste.
	const now = clipboardNow();
	const c = now?.payload;
	if (!c || (!c.blocks?.length && !c.parts?.length)) return null;
	const parts = c.parts ?? [];
	const loose = (c.blocks ?? []).filter((b) => b.part < 0);
	const bits = [];
	if (loose.length) {
		bits.push(loose.length === 1 ? loose[0].block.name : `${loose.length} blocks`);
	}
	if (parts.length) {
		bits.push(parts.length === 1 ? parts[0].name : `${parts.length} sub-systems`);
	}
	return {
		count: c.blocks?.length ?? 0,
		what: bits.join(' and '),
		system: c.system,
		whole: parts.length === 1 && !loose.length,
		// Which tab it came from, for a menu that can say so.
		from: now.from,
	};
}

/**
 * The diagram's context menu, opened from the tree or the Information view.
 *
 * There is one menu for a block, and it lives with the diagram because that is
 * where most of what it offers acts -- connecting two compartments, moving an
 * end, opening a sub-system. The other views ask for it rather than growing a
 * smaller one of their own, so that what a right-click does to a block does
 * not depend on which panel the block was found in.
 */
function blockMenu(name, ev) {
	if (!graph) return;
	if (!graph.openMenuFor(name, ev.clientX, ev.clientY)) {
		flash(`${name} no longer exists.`, 'warn');
	}
}

/**
 * Puts the blocks a menu is about onto the chart.
 *
 * A block is not a series: an indexed one is a series per index combination,
 * and `Dose` on a four-nuclide model is four lines. So this is by block rather
 * than by line -- which is the point of it, since the line picker above the
 * chart lists every series in the model and is a poor way to reach the one
 * block you happen to be looking at in the tree.
 *
 * A sub-system stands for everything inside it, at any depth, which is what
 * right-clicking one and asking for the chart has to mean.
 *
 * @param {string[]} names  blocks or sub-systems, qualified
 * @param {'add'|'only'} mode  beside what is there, or instead of it
 */
function chartBlocks(names, mode) {
	const r = state.results;
	if (!r) { flash('Run the model first.', 'warn'); return; }
	// The empty path is the model itself, and `isWithin(anything, '')` is true
	// -- so an empty name here would quietly mean "every series in the model".
	// The menu does not offer these on the tree's root row for that reason;
	// this is the other half of it, since one silent `''` would be a chart of
	// the whole model where a block was asked for.
	const paths = names.filter(Boolean);
	const want = new Set(paths);
	const hits = [];
	r.outputs.forEach((o, i) => {
		const block = o.block ?? '';
		if (want.has(block) || paths.some((p) => isWithin(block, p))) hits.push(i);
	});
	if (!hits.length) {
		flash(names.length === 1
			? `${names[0]} has no series — a disabled block produces none.`
			: 'None of these produced a series.', 'warn');
		return;
	}
	const before = mode === 'add' ? state.selected : [];
	// Order kept: what was already there stays where it was, and the new ones
	// follow, so adding to a chart does not restyle the lines already on it.
	const merged = [...before];
	for (const i of hits) if (!merged.includes(i)) merged.push(i);
	const room = merged.slice(0, MAX_SERIES);
	state.selected = room;
	renderPicker();
	renderChart();
	renderTable();
	const added = room.filter((i) => !before.includes(i)).length;
	const over = merged.length - room.length;
	const where = state.tab === 'table' ? 'table' : 'chart';
	flash(`${mode === 'add' ? 'Added' : 'Showing'} ${added} series`
		+ (mode === 'add' && before.length ? `, ${room.length} in the ${where}` : '')
		+ '.'
		+ (over
			? ` ${over} more would not fit: at most ${MAX_SERIES} are drawn.`
			: ''), over ? 'warn' : 'info');
}

/**
 * Everything a block can be given, in a dialog.
 *
 * The rail shows what a block *is* -- its name and the equation or value that
 * defines it. Its unit, its dimensions, a value per index, its colour and
 * shape and comment are all real and all editable, and all of them at once in
 * a narrow column is why this exists.
 */
function openBlockSettings(name) {
	if (!name || !ed.findBlock(state.raw, name)) return;
	// One window per block: asked again for a block whose window is open, it
	// comes to the front instead of opening a second copy of itself.
	const open = settingsWindows.get(name);
	if (open) {
		open.handle.focus();
		state.settingsFor = name;
		return;
	}
	// Which block this window is about. Its own, since several can be open:
	// a rename from inside it moves it on, and nothing else does.
	const win = { name, handle: null, id: ++settingsWindowCount };
	settingsWindows.set(name, win);
	state.settingsFor = name;
	win.handle = openModal({
		// What this kind of block is and what its window holds: see
		// ./blockinfo.js. Read when the (i) is pressed, from whichever block
		// the window is about by then. Keyed by the window, since two windows
		// can be about two kinds of block.
		info: {
			key: `dialog:block:${win.id}`,
			topic: () => blockTopic(ed.findBlock(state.raw, win.name)?.kind),
		},
		// A window, not a dialog: the page stays usable behind it, so a
		// second block's settings can be opened beside the first -- which is
		// how a value is read off one block and typed into another.
		floating: true,
		// The name it answers to in an equation, and -- when it has one --
		// what it is shown as, in brackets after it. The two are different
		// strings on purpose: `Water` is what the model is written in and
		// `H₂O` is what the diagram says, and a dialog titled only with the
		// second would be a dialog you could not find the block from.
		title: () => {
			const found = ed.findBlock(state.raw, win.name);
			if (!found || !ed.hasSymbol(found.block)) return win.name;
			return [win.name, ' (', ...symbolNodes(found.block.symbol), ')'];
		},
		subtitle: () => {
			const found = ed.findBlock(state.raw, win.name);
			if (!found) return '';
			const dims = ed.effectiveDims(state.raw, found.block);
			return `${found.kind.replace(/_/g, ' ')}`
				+ (dims.length ? ` \u00b7 indexed by ${dims.join(' \u00d7 ')}` : '');
		},
		build: (body) => {
			const found = ed.findBlock(state.raw, win.name);
			if (!found) {
				body.append(el('p', { className: 'hint' }, 'That block no longer exists.'));
				return;
			}
			renderInspector(body, state.raw, { kind: found.kind, name: win.name }, {
				atStart: startValueFor,
				onChange: (opts) => { state.settingsFor = win.name; modelChanged(opts); },
				onSelect: (sel) => {
					// Renaming from inside the window changes what it is
					// about; deleting from inside it closes it.
					if (!sel?.name) { win.handle?.close(); setSelection(null); return; }
					if (sel.name !== win.name) {
						settingsWindows.delete(win.name);
						win.name = sel.name;
						settingsWindows.set(win.name, win);
					}
					state.settingsFor = win.name;
					setSelection(sel);
					refreshModal();
				},
				onStatus: flash,
				// Which lists a block is indexed by is a property of the block;
				// what the lists are is not, so that edit happens on its own
				// tab, and the window gets out of the way.
				onOpenIndexList: (list) => { win.handle?.close(); openIndexLists(list); },
			}, { brief: false });
			// What is wrong with it, first: see fillSettingsProblems. Put in
			// after the inspector, which clears the body it is given.
			const faults = el('div', { className: 'settings-problems', role: 'alert' });
			faults.dataset.block = win.name;
			body.prepend(faults);
			fillSettingsProblems();
		},
		onClose: () => {
			settingsWindows.delete(win.name);
			if (state.settingsFor === win.name) state.settingsFor = [...settingsWindows.keys()].pop() ?? null;
		},
	});
	// The window with the keyboard in it is the one an edit is named after in
	// the undo history: see `modelChanged`.
	win.handle.dialog.addEventListener('focusin', () => { state.settingsFor = win.name; });
}

/**
 * The block settings windows that are open, by the block each is about. See
 * `openBlockSettings`.
 */
const settingsWindows = new Map();
let settingsWindowCount = 0;

/**
 * Copy format: how a block looks, kept for Paste format -- its colour and
 * shape, or a connection's colour, weight and line style. The look only: the
 * block clipboard is left alone, so a copy waiting to be pasted survives it.
 * Kept across models, since a look belongs to no model in particular.
 */
function copyFormat(name) {
	const format = ed.formatOf(state.raw, name);
	if (!format) { flash(`${ed.baseName(name)} has no look of its own to copy.`, 'warn'); return; }
	state.formatClip = format;
	flash(`${ed.baseName(name)}\u2019s ${format.kind === 'node' ? 'colour and shape' : 'colour, weight and line style'} `
		+ 'copied. Paste format — on a block\u2019s menu, or \u2325\u2318V — puts it on the blocks selected.', 'info');
}

/** Paste format: the copied look onto blocks, one step to undo. */
function pasteFormat(names) {
	const format = state.formatClip;
	if (!format) { flash('Nothing copied yet: Copy format on a block first.', 'warn'); return; }
	let changed;
	try {
		changed = ed.applyFormat(state.raw, names, format);
	} catch (e) {
		flash(e.message, 'warn');
		return;
	}
	if (!changed.length) { flash(`They already look like ${ed.baseName(format.from)}.`, 'info'); return; }
	// How a block is drawn changes no number.
	modelChanged({ layoutOnly: true });
	flash(`${changed.length === 1 ? ed.baseName(changed[0]) : `${changed.length} blocks`} now `
		+ `${changed.length === 1 ? 'looks' : 'look'} like ${ed.baseName(format.from)}.`, 'info');
}

/** Matches are marked on the diagram too, and the rest recede. */
function applySearchToGraph() {
	if (!graph) return;
	const filter = treeFilter();
	const filtering = !!filter.query.trim() || filter.kinds.size > 0 || !!filter.only;
	graph.setSearch(filtering
		? new Set(ed.searchBlocks(state.raw, filter).map((b) => b.name))
		: null);
}

/** Shows the Index lists tab, on a particular list when one is named. */
function openIndexLists(name = null) {
	if (name) selectIndexList(name);
	selectTab('indexlists');
}

function renderIndexListsView() {
	renderIndexLists($('#panel-indexlists'), state.raw, {
		onChange: modelChanged,
		onStatus: flash,
		// What the pane is for, behind an (i) at the end of its heading.
		info: () => infoButton('panel:indexlists', () => panelTopic('indexlists')),
		// Imported on the click, not at boot: the ICRP 107 table is 117 KB of
		// nuclide data, and a session that never opens this dialog should not
		// pay for it.
		onBrowseNuclides: async () => {
			try {
				const { openNuclidePicker } = await import('./nuclidepicker.js');
				openNuclidePicker(state.raw, { onChange: modelChanged, onStatus: flash });
			} catch (e) {
				flash(`Could not load the nuclide database: ${e.message}`, 'warn');
			}
		},
	});
}

/**
 * The from/to grid, built when it is going to be looked at.
 *
 * It is (compartments + paths + 1) squared: two hundred compartments is forty
 * thousand cells. It was rebuilt on every edit and on every change of
 * selection -- `setSelection` calls this, so every click anywhere in the
 * application did it -- whether or not its tab was the one in front. What is
 * remembered is which model revision the grid on screen was built from; a
 * selection that moves within the same revision moves the highlight instead.
 */
let matrixStale = true;
let matrixBuilt = { model: null, rev: -1 };

function renderMatrixView() {
	if (state.tab !== 'matrix') { matrixStale = true; return; }
	if (!matrixStale && matrixBuilt.model === state.raw && matrixBuilt.rev === state.rev) {
		markSelection($('#panel-matrix'), state.selection);
		return;
	}
	drawMatrix();
}

function drawMatrix() {
	// Before any model has been loaded there is nothing to draw and nothing to
	// record: `selectTab` runs during boot -- `?tab=matrix` opens straight on
	// this one -- and the model arrives a fetch later. Leaving `matrixStale`
	// set is the point of returning rather than rendering an empty grid: the
	// render that follows the load is the one that builds it.
	if (!state.raw) return;
	matrixStale = false;
	matrixBuilt = { model: state.raw, rev: state.rev };
	renderMatrix($('#panel-matrix'), state.raw, state.selection, {
		onChange: modelChanged,
		onSelect: setSelection,
		onStatus: flash,
		onOpenSettings: openBlockSettings,
		// Folding a sub-system changes nothing about the model, so it does not
		// go through `modelChanged`: the grid is redrawn and that is all.
		onToggleSystem: (path) => {
			if (state.matrixOpen.has(path)) {
				// Folding a sub-system folds what is inside it too: reopening
				// it to find its children still spread out is not what closing
				// and opening something means.
				for (const p of [...state.matrixOpen]) {
					if (p === path || ed.isWithin(p, path)) state.matrixOpen.delete(p);
				}
			} else {
				// Opening one opens the way to it, so a sub-system reached
				// from a fold several deep does not vanish behind a closed
				// parent.
				let at = path;
				while (at) { state.matrixOpen.add(at); at = ed.parentOf(at); }
			}
			drawMatrix();
		},
	}, { open: state.matrixOpen });
}

// --- sidebar ------------------------------------------------------------------

/**
 * Which sections of the left panel start open.
 *
 * Open by default are the ones you come back to while iterating on a model.
 * Closed are the ones set up once and visible elsewhere anyway: the name and
 * description are in the header, and a block's dimensions show on the block.
 */
const SECTION_OPEN = {
	model: false,
	// Closed: the settings are read once and changed rarely, and the panel
	// they share is the tree's as well -- open by default they took the top
	// two fifths of it before the model had been looked at.
	simulation: false,
};

/**
 * One collapsible section of the top of the left panel.
 *
 * Two of them -- the model's name and the simulation settings -- which share
 * the panel with the tree and the reading view below. Folding one gives its
 * height to the tree, which is the point of their being foldable now that the
 * three are in one column.
 *
 * Open state lives in `state`, not in the DOM: every edit re-renders this part
 * of the panel, so anything held only in the markup would be lost on the next
 * keystroke.
 */
function section(id, title, badge, badgeTitle = '', defaultOpen = null, info = null) {
	return part({
		id,
		title,
		badge,
		badgeTitle,
		info,
		open: sectionOpen(id, defaultOpen),
		// Re-rendered on opening, because a section that is closed does not
		// build its rows at all -- a model with a thousand transfers would pay
		// for them on every keystroke whether or not anyone could see them.
		// Opening one therefore has to go and get them.
		onToggle: (open) => {
			state.sbSections[id] = open;
			if (open) renderSidebar();
		},
	});
}

/** What the user last chose for a section, or what it should start as. */
function sectionOpen(id, defaultOpen = null) {
	return state.sbSections[id] ?? defaultOpen ?? SECTION_OPEN[id] ?? true;
}

/** Opens a section and re-renders, so a field inside it can be reached. */
function openSection(id) {
	if (state.sbSections[id] === true) return;
	state.sbSections[id] = true;
	renderSidebar();
}

/**
 * When the model was made and last saved, as the file records it: a line
 * under the author, read-only, since both are stamped by Save itself.
 */
function modelDatesLine(raw) {
	const created = ed.readStamp(raw.created);
	const saved = ed.readStamp(raw.saved);
	const day = (d) => d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
	const time = (d) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
	const parts = [];
	if (created) parts.push(`Created ${day(created)}`);
	if (saved) {
		// The day once when both are the same day: "saved 14:03" reads better
		// than the date twice.
		const sameDay = created && day(created) === day(saved);
		parts.push(`${parts.length ? 'saved' : 'Saved'} ${sameDay ? '' : `${day(saved)}, `}${time(saved)}`);
	}
	const text = parts.length ? parts.join(' · ') : 'Not saved yet — Save records when it was made and saved.';
	return el('p', {
		className: 'hint model-dates',
		title: [
			created ? `Created ${created.toLocaleString()}` : 'No date of making recorded',
			saved ? `Last saved ${saved.toLocaleString()}` : 'Not saved yet',
			'Both are in the file as created and saved, and Save writes them.',
		].join('\n'),
	}, text);
}

/**
 * The model's own name and description.
 *
 * They were previously editable only by hand in the JSON tab, which is an odd
 * place for the two most visible fields in the application. Both are committed
 * on `change` -- blur or Enter -- rather than on every keystroke, so a re-render
 * cannot pull the caret out from under the typist.
 */
function renderModelGroup(raw) {
	const group = section('model', 'Model', undefined, '', null,
		infoButton('panel:model', () => panelTopic('model')));

	const name = el('input', {
		type: 'text', id: 'model-name', className: 'stack-input',
		value: raw.name ?? '', placeholder: ed.UNTITLED, spellcheck: false,
	});
	name.addEventListener('change', () => {
		ed.setModelName(raw, name.value);
		// The name changes nothing about the numbers, so this must not mark
		// the model as needing a re-run.
		modelChanged({ layoutOnly: true });
	});
	name.addEventListener('keydown', (e) => { if (e.key === 'Enter') name.blur(); });

	const desc = el('textarea', {
		id: 'model-description', className: 'stack-input model-desc',
		value: raw.description ?? '', rows: 3, spellcheck: false,
		placeholder: 'What this model is, and where it came from',
	});
	desc.addEventListener('change', () => {
		ed.setModelDescription(raw, desc.value);
		modelChanged({ layoutOnly: true });
	});

	const author = el('input', {
		type: 'text', id: 'model-author', className: 'stack-input',
		value: ed.modelAuthor(raw), spellcheck: false,
		placeholder: 'Who wrote it — a name, a team, an organisation',
	});
	author.addEventListener('change', () => {
		ed.setModelAuthor(raw, author.value);
		modelChanged({ layoutOnly: true });
	});
	author.addEventListener('keydown', (e) => { if (e.key === 'Enter') author.blur(); });

	group.append(
		el('div', { className: 'field-stack' },
			el('label', { htmlFor: 'model-name' }, 'Name'), name),
		el('div', { className: 'field-stack' },
			el('label', { htmlFor: 'model-description' }, 'Description'), desc),
		el('div', { className: 'field-stack' },
			el('label', { htmlFor: 'model-author' }, 'Author'), author),
		modelDatesLine(raw),
	);

	// --- review -----------------------------------------------------------
	// A switch and a tally. Off by default and off in every model that has not
	// asked for it: a review is a process somebody decides to run.
	{
		const on = qa.enabled(raw);
		const box = el('input', { type: 'checkbox', id: 'qa-on', checked: on });
		box.addEventListener('change', () => {
			qa.setEnabled(raw, box.checked);
			// Records are kept either way, as AMBER's are: switching this off
			// is hiding the feature, not discarding somebody's review.
			modelChanged({ layoutOnly: true });
		});
		group.append(el('div', { className: 'field' },
			el('label', { htmlFor: 'qa-on', title: 'Record which definitions have been '
				+ 'reviewed and approved, and notice when an approval lapses because '
				+ 'the block — or something it is worked out from — has changed since.' },
			'Track review'), box));

		if (on) {
			const n = qa.summary(raw);
			const behind = n.stale + n.review;
			const line = el('button', {
				type: 'button',
				className: `qa-tally${behind ? ' is-behind' : ''}`,
				title: 'Show the blocks a review has not signed off',
			},
			`${n.approved.toLocaleString()} approved`,
			behind ? `, ${behind.toLocaleString()} to review` : '',
			n.none ? `, ${n.none.toLocaleString()} not looked at` : '',
			n.locked ? ` · ${n.locked} locked` : '');
			line.addEventListener('click', () => {
				const found = Q.runQuery(raw, 'notApproved', { qa: qa.statuses(raw) });
				state.search.only = found;
				state.search.onlyLabel = 'That are not approved';
				state.search.query = '';
				renderRail();
				renderSearch();
			});
			group.append(el('div', { className: 'field' }, el('label', {}, ''), line));
		}
	}

	// --- versions ---------------------------------------------------------
	// What changed: against the file as it was opened, or against another
	// file. GoldSim keeps versions inside the file and prints the difference
	// between any two; the report is the useful half of that, and the two
	// files a reviewer actually has are these.
	{
		const cmp = el('button', {
			type: 'button', className: 'ghost sb-action sb-compare', 'aria-haspopup': 'menu',
		}, 'Compare with \u25be');
		cmp.title = 'A version report: every block, list, nuclide and setting that differs '
			+ 'between this model and another version of it.';
		cmp.addEventListener('click', (ev) => {
			const at = ev.currentTarget.getBoundingClientRect();
			const opened = state.opened?.text;
			openMenu({
				x: at.left, y: at.bottom, title: 'compare',
				items: [
					{ label: 'The model as it was opened', disabled: !opened,
						title: opened ? `What has changed since ${state.opened.label} was opened.`
							: 'Nothing has been opened yet.',
						onPick: () => compareWithOpened() },
					{ label: 'Another file\u2026',
						title: 'Pick a model file — .json, .zip, .eco or .eas — and see how this '
							+ 'model differs from it.',
						onPick: () => compareWithFile() },
				],
			});
		});
		group.append(el('div', { className: 'field' }, el('label', {}, ''), cmp));
	}
	return group;
}

/**
 * Where the caret is in the panel, so that a commit does not throw it out.
 *
 * Every commit rebuilds this whole panel, and the field being typed in is one
 * of the elements `replaceChildren` destroys -- so pressing Enter in a value
 * used to commit it and drop focus on `<body>`. At 62px rows that was a thing
 * you noticed once; at 24px the panel is a list you walk with Tab and Enter,
 * and being thrown out of it on every value is the difference between a panel
 * you can work down and one you have to keep clicking back into.
 *
 * Keyed by what survives the rebuild: the row's block name, an id, or the
 * simulation setting the field edits. Nothing is restored unless the caret was
 * in this panel to begin with, so this can never take focus from anywhere
 * else -- including the `+` button's own flow, which focuses the row it made
 * once the rebuild is over.
 */
function sbCaret() {
	const sb = $('#sidebar');
	const node = document.activeElement;
	if (!sb || !node || !sb.contains(node)) return null;
	if (!['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName)) return null;
	const key = node.id ? { id: node.id }
		: node.dataset.sim ? { sim: node.dataset.sim }
			: node.closest('[data-block]') ? { block: node.closest('[data-block]').dataset.block }
				: null;
	if (!key) return null;
	return { ...key, at: [node.selectionStart, node.selectionEnd] };
}

function sbRestore(was) {
	if (!was) return;
	const field = was.id
		? document.querySelector(`#sidebar #${was.id}`)
		: was.sim
			? document.querySelector(`#sidebar [data-sim="${was.sim}"]`)
			// Scanned rather than selected: a qualified name carries dots, and
			// an attribute selector would need them escaped.
			: [...document.querySelectorAll('#sidebar [data-block]')]
				.find((n) => n.dataset.block === was.block)?.querySelector('input');
	if (!field) return;
	field.focus();
	// Only a text-ish control has a selection to put back.
	try { field.setSelectionRange(was.at[0], was.at[1]); } catch { /* not one */ }
}

/**
 * What an empty box of a solver setting shows, greyed: `auto: 1e6`, `auto:
 * none`, `auto: estimated`. The number where there is one; a word where the
 * solver works it out during the run.
 */
function autoPlaceholder(d) {
	if (d.value === Infinity) return 'auto: no limit';
	if (typeof d.value === 'number') return `auto: ${fmtSetting(d.value)}`;
	if (d.value == null) return d.short ? `auto: ${d.short}` : 'auto';
	return `auto: ${d.value}`;
}

function renderSidebar() {
	const raw = state.raw;
	// `#sb-top`, not `#sidebar`: the tree and the Information card are the
	// sidebar's other children, and an edit does not rebuild them.
	const sb = $('#sb-top');
	const caret = sbCaret();
	sb.replaceChildren();

	sb.append(renderModelGroup(raw));

	const sim = raw.simulation ?? {};
	// The two facts worth seeing without opening it: how long the run is, and
	// what solves it.
	const group = section('simulation', 'Simulation',
		`${fmtTime(sim.start_time)}–${fmtTime(sim.end_time)} ${sim.time_unit ?? 'year'}`
		+ ` \u00b7 ${solverLabel(sim.solver ?? DEFAULT_SOLVER)}`,
		'', null, infoButton('panel:simulation', () => panelTopic('simulation')));

	// Which settings the scan is currently objecting to, so the field that is
	// wrong is the field that is marked -- the same signal a broken equation
	// gets in the panel below.
	const simProblem = new Map(
		state.problems.filter((p) => p.kind === 'simulation').map((p) => [p.key, p.message]),
	);

	// The (i) beside each row, and what it opens: see ./infopanel.js and
	// ./siminfo.js. Instead of the tooltips these rows had -- the panel says
	// what a tooltip could, and the defaults it could not. Worked out when the
	// panel is drawn, so what it says is the model as it stands then.
	const simCtx = () => ({
		sim: state.raw?.simulation ?? {},
		solver: state.raw?.simulation?.solver ?? DEFAULT_SOLVER,
		solverLabel,
		scenarios: ed.scenarioNames(state.raw),
		scenario: ed.activeScenario(state.raw),
		series: ed.outputSeries(state.raw).map((spec) => ed.describeSeries(
			spec, Number(state.raw.simulation?.start_time ?? 0), Number(state.raw.simulation?.end_time ?? 0),
		)),
	});
	const info = (key) => infoButton(`sim:${key}`, () => simTopic(key, simCtx()));
	// A row: its name, its control, and its (i) after the control, in a column
	// of its own down the right-hand edge of the panel -- the same column the
	// section headings keep theirs in, so every (i) is in one line.
	const infoRow = (cls, label, control, key) => el('div', { className: `${cls} has-info` },
		label, control, info(key));

	const numField = (key, unit, { placeholder = '' } = {}) => {
		const label = SIM_LABELS[key] ?? key;
		const wrong = simProblem.get(key);
		const input = el('input', {
			type: 'text', value: String(sim[key] ?? ''), spellcheck: false,
			// What an empty box comes to, greyed in it: the question an
			// empty box asks.
			placeholder,
			...(wrong ? { title: wrong } : {}),
		});
		if (wrong) input.classList.add('is-invalid');
		// What sbRestore finds it by after the rebuild this field's own commit
		// causes: these rows have no block name and no id.
		input.dataset.sim = key;
		input.addEventListener('change', () => {
			const v = Number(input.value);
			// A number is written even when it is not a usable one -- a zero
			// tolerance, an end time before the start -- because the field
			// then shows what was typed, marked, with the reason in the strip
			// above. Reverting it silently is how a mistake becomes a mystery.
			// Something that is not a number at all is not an edit at all.
			if (Number.isFinite(v)) {
				raw.simulation = { ...raw.simulation, [key]: v };
				modelChanged({ solveOnly: SOLVE_ONLY_SETTINGS.has(key) });
			} else {
				input.value = String(raw.simulation?.[key] ?? '');
				flash(`'${input.value}' — ${label.toLowerCase()} has to be a number`, 'warn');
			}
		});
		return infoRow('field', el('label', {}, label, unit ? el('span', { className: 'unit' }, ` ${unit}`) : ''),
			input, key);
	};

	/**
	 * A switch, for a setting that is on or off.
	 *
	 * The only one so far is the floor over every compartment, and it earns a
	 * row here rather than a per-block edit because it is a question about the
	 * run -- *is this model allowed to go negative at all* -- which is usually
	 * asked while looking at a result that has gone flat.
	 */
	// `on` is what an absent key means. `non_negative` is a master switch that
	// is on unless a model turns it off, so absent is on; the opt-in ones are
	// off unless a model asks, and `sim[key] !== false` read those as ticked
	// while the run had them off -- a switch that lied about the setting it
	// controls, for as long as the mass-balance audit has existed.
	const boolField = (key, { on = true, disabled = '' } = {}) => {
		const label = SIM_LABELS[key] ?? key;
		const checked = on ? sim[key] !== false : sim[key] === true;
		const box = el('input', {
			type: 'checkbox', checked, disabled: !!disabled,
			...(disabled ? { title: disabled } : {}),
		});
		box.dataset.sim = key;
		box.addEventListener('change', () => {
			raw.simulation = { ...raw.simulation, [key]: box.checked };
			modelChanged({ solveOnly: SOLVE_ONLY_SETTINGS.has(key) });
		});
		// `is-wide` gives the label its natural width instead of the 90px name
		// column: a switch needs 13px of value column, and `Cannot go negative`
		// does not fit in what is left. It reads as a phrase with a box after
		// it, which is what it is.
		return infoRow('field is-wide', el('label', {}, label), box, key);
	};

	// `describe` gives each option a tooltip; `wide` gives the control the room
	// instead of the label, for a choice whose names are longer than a number.
	const selField = (key, options, { wide = false } = {}) => {
		const label = SIM_LABELS[key] ?? key;
		const sel = el('select', {});
		const wrong = simProblem.get(key);
		if (wrong) { sel.classList.add('is-invalid'); sel.title = wrong; }
		// Found by sbRestore after the rebuild this select's own commit
		// causes: arrowing through a closed select commits on every key, so
		// without it the second arrow key goes to the page instead.
		sel.dataset.sim = key;
		for (const [v, t] of options) {
			sel.append(el('option', { value: v, selected: (sim[key] ?? '') === v }, t));
		}
		sel.addEventListener('change', () => {
			raw.simulation = { ...raw.simulation, [key]: sel.value };
			modelChanged({ solveOnly: SOLVE_ONLY_SETTINGS.has(key) });
		});
		return infoRow(wide ? 'field is-wide' : 'field', el('label', {}, label), sel, key);
	};

	/**
	 * How the output times are chosen.
	 *
	 * Its own function rather than a `selField` because two of the four
	 * choices are not spacings at all: one hands the question to the solver,
	 * and one opens an editor. Changing it goes through the domain, which
	 * seeds a series list from whatever shorthand was in force so that moving
	 * to `series` starts from the grid the model already had.
	 */
	const spacingField = () => {
		const sel = el('select', {});
		sel.dataset.sim = 'spacing';
		const options = [
			['log', 'Logarithmic', 'Equal ratios, from the first point the scale can '
				+ 'hold to the end. What a result spanning decades is read in — and '
				+ 'nothing between the start and that first point is saved.'],
			['linear', 'Linear', 'Equal steps from start to end.'],
			['series', 'Several series…', 'A list of series combined into one set of '
				+ 'times: a logarithmic one for the run and an even one for its first '
				+ 'year, say, plus any times written out by hand.'],
			['solver', 'The solver’s own points', 'No grid: the result is reported at '
				+ 'every step the solver takes. It already takes small steps where the '
				+ 'answer is moving and large ones where it is not, which is the '
				+ 'distribution a result wants — and nothing has to be chosen in '
				+ 'advance.'],
			['both', 'Series and the solver’s points', 'Both of the above, merged: the '
				+ 'times you asked for, and every step the solver took between them.'],
		];
		for (const [v, label] of options) {
			sel.append(el('option', { value: v, selected: sim.spacing === v }, label));
		}
		sel.addEventListener('change', () => {
			try {
				ed.setSpacing(raw, sel.value);
				modelChanged();
				// Straight into the editor: choosing a list of series is
				// asking to edit them, and the seeded one is not the answer.
				if (sel.value === 'series' || sel.value === 'both') openSavedTimes();
			} catch (e) { flash(e.message, 'warn'); }
		});
		return infoRow('field', el('label', {}, SIM_LABELS.spacing), sel, 'spacing');
	};

	/**
	 * What the series come to, and the way in to editing them.
	 *
	 * The value *is* the button: a label narrow enough for this column cannot
	 * also carry a link, and what anyone wants from this row is either the
	 * count or the editor.
	 */
	const savedTimesField = () => {
		const times = ed.outputTimes(raw);
		const series = ed.outputSeries(raw);
		// A series with every time outside the run saves nothing. Not refused
		// -- the solver never reaches those times -- but said, here and in
		// the editor, so it is not mistaken for one that is working.
		const outside = new Set(ed.outsideSeries(raw));
		const button = el('button', {
			type: 'button',
			className: `sb-summary${outside.size ? ' is-warned' : ''}`,
		}, `${times.length} time${times.length === 1 ? '' : 's'}, ${series.length} series`
			+ (sim.spacing === 'both' ? ' + steps' : '')
			+ (outside.size ? ` \u2014 ${outside.size} outside the run` : ''));
		button.addEventListener('click', openSavedTimes);
		return infoRow('field', el('label', {}, 'Saved times'), button, 'saved_times');
	};

	// Which scenario is live. The usual arrangement is one simulation per
	// scenario; this
	// tool runs the one selected here, and every block indexed by the scenario
	// list is read at that index. Only shown when the model has any -- most do
	// not, and a control for a choice of one is noise.
	const scenarios = ed.scenarioNames(raw);
	if (scenarios.length) {
		const sel = el('select', {});
		sel.dataset.sim = 'scenario';
		const active = ed.activeScenario(raw);
		for (const name of scenarios) {
			sel.append(el('option', { value: name, selected: name === active }, name));
		}
		sel.addEventListener('change', () => {
			ed.setScenario(raw, sel.value);
			modelChanged();
		});
		// Which scenario runs is a simulation setting; what the scenarios *are*
		// is an index list, and this is the only place the two meet.
		//
		// `1 of 3` left the label for the select's own tooltip: on one line the
		// label is a column the names have to be read past, and the count is
		// the least of the three things in it -- the select lists them all when
		// it is opened, and the `edit` link is the only route from here to
		// where they are defined.
		const edit = el('button', { type: 'button', className: 'link-btn' }, 'edit');
		edit.addEventListener('click', () => openIndexLists(ed.scenarioList(raw)?.name));
		// `field`, not `field is-wide`: the wide variant sizes its label column
		// to the label, which put this select at a different left edge and a
		// different width from every other control in the group. `Scenario`
		// fits the shared name column, so it shares it -- one edge down the
		// panel, the way the buttons below do.
		group.append(infoRow('field', el('label', {}, 'Scenario',
			el('span', { className: 'unit' }, ' \u00b7 '), edit), sel, 'scenario'));
		// Which run beside it: every scenario as a chip, ticked to run with
		// the selected one, each in a worker of its own, and be drawn with it.
		// The selected one is always on -- it is the run -- and is changed
		// above rather than here.
		if (scenarios.length > 1) {
			const running = scenariosToRun(raw, state.scenarioChoice);
			const box = el('div', { className: 'search-kinds sb-scenarios' });
			for (const name of scenarios) {
				const isActive = name === active;
				const on = running.includes(name);
				const entry = state.scenarioRuns.get(name);
				const status = isActive
					? 'the selected scenario, which always runs; choose another under Scenario'
					: !on ? 'not run \u2014 click to run it beside the selected one'
						: entry?.error ? `did not run: ${entry.error}`
							: entry?.running ? 'running'
								: entry?.queued ? 'waiting for a core'
									: entry?.r ? 'run \u2014 click to stop running it'
										: 'runs with the next run';
				const chip = el('button', {
					type: 'button',
					className: `search-chip${on ? ' is-on' : ''}${isActive ? ' is-fixed' : ''}`
						+ `${entry?.error && on && !isActive ? ' is-failed' : ''}`,
					title: `${name}: ${status}`,
				}, name);
				chip.setAttribute('aria-pressed', String(on));
				chip.dataset.scenarioRun = name;
				if (!isActive) chip.addEventListener('click', () => chooseScenario(name, !on));
				box.append(chip);
			}
			group.append(infoRow('field field-chips', el('label', {}, 'Run'), box, 'run_together'));
		}
	}

	group.append(
		// `Start`, not `Start time`: the unit suffix beside it already says
		// what kind of quantity it is, and in a column this narrow the word
		// `time` costs 23px on two rows to repeat the section's own title.
		// What each of these is -- what the row used to say on hover, and
		// what an empty box comes to -- is in ./siminfo.js, behind the (i).
		numField('start_time', sim.time_unit ?? 'year'),
		numField('end_time', sim.time_unit ?? 'year'),
		// Only where it means something: a list of series carries its own
		// counts, and the solver's own steps are however many it takes.
		...(['series', 'solver', 'both'].includes(sim.spacing)
			? [] : [numField('output_points', '')]),
		spacingField(),
		...(sim.spacing === 'series' || sim.spacing === 'both'
			? [savedTimesField()] : []),
		selField('time_unit', [
			['year', 'Years'], ['day', 'Days'], ['hour', 'Hours'],
			['minute', 'Minutes'], ['second', 'Seconds'],
		]),
		// Labelled by what the solver is for, not by which method it
		// is; the id stays in the information panel and in the project file.
		// In the same column as everything above it: a control that starts
		// further left than the eight fields around it reads as a different
		// kind of thing, and the longest name -- "stiff, var. order" -- fits
		// the value column at the panel's default width.
		// A solver that needs a download is marked in the list rather than only
		// in its description: it is the one choice here with a consequence
		// outside the model -- it will not run on a machine with no network.
		selField('solver',
			// The arrow leads rather than trails. In the column the other eight
			// fields use there is room for the three local solvers and none for
			// the longest SciPy name, and a select clips its tail -- so an arrow
			// at the end is the first thing lost, which is the one part of the
			// label that must not be. The open list is not clipped at all.
			SOLVER_IDS.map((id) => [id, (solverIsRemote(id) ? '\u2193 ' : '') + solverLabel(id)])),
		numField('rtol', ''),
		numField('abstol', ''),
		// Cannot go negative, Mass balance and Split into parts are under
		// Advanced settings, below: switches on how any solve behaves, set
		// once and left.
	);
	// dy/dp needs no distributions -- it is a derivative at the values the
	// model holds -- so it is offered whatever the model carries.
	{
		const dydp = el('button', { type: 'button', className: 'ghost sb-action sb-dydp' },
			'Sensitivity\u2026');
		dydp.addEventListener('click', openLocalSensitivity);
		// `field`, not `field is-wide`: the wide variant sizes its label column
		// to the label, which put each of these buttons at a different x and a
		// different width from the settings above them. The plain one shares
		// the column the inputs use, so the three buttons and every input in
		// this group are one edge down the panel.
		group.append(infoRow('field', el('label', {}, 'dy/dp'), dydp, 'dydp'));
	}
	// The other direction: not what this model gives, but what the inputs
	// would have to be for it to give something. Offered whenever there is a
	// parameter to vary, which is every model worth calibrating.
	{
		const fit = el('button', { type: 'button', className: 'ghost sb-action sb-opt' },
			'Optimise\u2026');
		fit.addEventListener('click', openOptimise);
		group.append(infoRow('field', el('label', {}, 'Calibration'), fit, 'calibration'));
	}
	// Only where there is something to sample. A model with no distribution
	// would run a thousand identical realisations, and offering that is worse
	// than not offering it.
	if (ed.hasDistributions(raw)) {
		const go = el('button', { type: 'button', className: 'ghost sb-action sb-prob' },
			'Probabilistic\u2026');
		go.addEventListener('click', openProbabilistic);
		const row = infoRow('field', el('label', {}, 'Uncertainty'), go, 'uncertainty');
		group.append(row);
		// Only once there is a sample to read: sensitivity here is computed
		// from the realisations already drawn, not from further runs.
		if (currentProb()) {
			const why = el('button', { type: 'button', className: 'ghost sb-action sb-why' },
				'What drove it\u2026');
			why.addEventListener('click', () => openSensitivity());
			group.append(infoRow('field', el('label', {}, ''), why, 'what_drove'));
		}
		// The rest of what a sample can be asked, and the runs that need no
		// sample. A menu rather than five more buttons: the panel is 306
		// pixels and each of these is asked for once a run stands, where
		// Probabilistic… and What drove it… are the two that are pressed.
		const more = el('button', {
			type: 'button', className: 'ghost sb-action sb-more', 'aria-haspopup': 'menu',
		}, 'Analyse \u25be');
		more.addEventListener('click', (ev) => {
			const has = !!currentProb();
			const at = ev.currentTarget.getBoundingClientRect();
			openMenu({
				x: at.left, y: at.bottom, title: 'analyse',
				items: [
					{ label: 'Distribution summary\u2026', disabled: !has,
						title: has ? 'One output at one time as a distribution: mean and its bounds, '
							+ 'percentiles, skewness, and a calculator between value and probability.'
							: 'Needs a probabilistic run.',
						onPick: () => openDistribution() },
					{ label: 'Categories of realisation\u2026',
						title: 'Sort the realisations by what they did — peak above a limit, failure '
							+ 'before a year — and show only the ones you mean. Saved with the model.',
						onPick: () => openCategories() },
					{ label: 'Bands\u2026',
						title: 'Which percentiles the bands are drawn at, and whether the mean is '
							+ 'drawn beside the median.',
						onPick: () => openBands() },
					{ separator: true },
					{ label: 'Tornado\u2026',
						title: 'Every sampled input swung on its own to a low and a high percentile '
							+ 'with the rest held: which inputs move this output at all. Needs no sample.',
						onPick: () => openTornado() },
					{ label: 'Global sensitivity\u2026',
						title: 'Morris, Sobol, eFAST, RBD-FAST, a fractional factorial, DGSM, the radial '
							+ 'design or Shapley effects: an experiment of its own over the distributions, '
							+ 'priced before it runs. Needs no sample.',
						onPick: () => openGsa() },
					{ label: 'Global sensitivity result\u2026', disabled: !state.gsa,
						title: state.gsa
							? 'The last design’s table again, from the runs already made — any output, '
								+ 'any reading, nothing run again.'
							: 'Needs a global sensitivity run.',
						onPick: () => showGsa() },
					{ label: 'Replay a realisation\u2026', disabled: !has,
						title: has ? 'Run one realisation of the probabilistic run again as an '
							+ 'ordinary run, every series of it.' : 'Needs a probabilistic run.',
						onPick: () => openReplay() },
				],
			});
		});
		group.append(infoRow('field', el('label', {}, ''), more, 'analyse'));
	}
	// --- the solver's own settings ------------------------------------------
	//
	// Only the ones the chosen solver reads, and the rest *named* underneath
	// rather than simply gone: a knob that silently does nothing is worse than
	// a missing one, because nothing on screen says which it is. Which solver
	// reads what is in SOLVER_OPTIONS (../ode/solvers.js), beside the code
	// that passes them on, because that is the only place the answer stays
	// honest.
	{
		const id = sim.solver ?? DEFAULT_SOLVER;
		const keys = solverOptions(id);
		const dropped = solverIgnores(id);
		{
			// First the three every solver honours: how the solve is allowed to
			// behave rather than what the model says, each set once and left --
			// which is why they are folded away with the rest. Cannot go
			// negative is the file's `saturation-enabled`, in the one form this
			// tool carries; Split into parts solves a model that falls apart
			// into independent parts -- a decay chain each, on an assessment --
			// a part per core, each at its own steps.
			const box = el('div', { className: 'sim-solver-opts' },
				boolField('non_negative'),
				boolField('mass_balance', { on: false }),
				selField('split', SPLIT_MODES.map(([v, label]) => [v, label])));
			// Then the chosen solver's own, under a line that says so.
			if (keys.length) box.append(el('p', { className: 'sim-opts-head' }, 'The solver\u2019s own settings'));
			// What an empty box comes to for this solver and this run, so that
			// an empty box answers its own question: greyed in a number box,
			// and named in the `auto` of a choice. See solverDefault in
			// ../ode/solvers.js.
			const span = Number(sim.end_time ?? 0) - Number(sim.start_time ?? 0);
			for (const key of keys) {
				const info = SOLVER_OPTION_INFO[key];
				const d = solverDefault(key, id, { span });
				if (info.kind === 'switch') {
					box.append(boolField(key, { on: info.on }));
				} else if (info.kind === 'choice') {
					const name = (v) => {
						const c = info.choices.find((x) => String(Array.isArray(x) ? x[0] : x) === String(v));
						return c == null ? String(v) : Array.isArray(c) ? c[1] : String(c);
					};
					box.append(selField(key, [
						// Unset is the solver's own, named: `auto (max)` says
						// both that nothing was chosen and what that means.
						['', `auto${d.value != null && d.value !== 'auto' ? ` (${name(d.value)})` : ''}`],
						// A choice is a value, or a value and what to call it:
						// `numeric` is shown as `finite differences`.
						...info.choices.map((c) => (Array.isArray(c) ? [String(c[0]), c[1]] : [String(c), String(c)])),
					]));
				} else {
					const unit = info.unit === true ? (sim.time_unit ?? 'year') : (info.unit || '');
					box.append(numField(key, unit, { placeholder: autoPlaceholder(d) }));
				}
			}
			// Inside the fold, under the settings it is about, as facsimile.html
			// and rtm.html have it. A solver that reads none of them (SciPy's)
			// has this under the three switches, and no heading over nothing.
			if (dropped.length) {
				const last = dropped.length > 1 ? ` and ${dropped[dropped.length - 1]}` : '';
				const list = dropped.length > 1
					? dropped.slice(0, -1).join(', ') + last : dropped[0];
				box.append(el('p', { className: 'sim-dropped' },
					`${solverLabel(id)} does not read ${list}, so `
					+ `${dropped.length === 1 ? 'it is' : 'they are'} not shown.`));
			}
			// The fold is remembered the way every other section here is: the
			// panel rebuilds on each edit, so a fold that did not would close
			// itself the moment one of its own fields was typed in.
			// `Advanced settings`, as facsimile.html and rtm.html call theirs: the
			// same settings go by the same names in all three.
			const fold = el('details', { className: 'sim-opts', open: sectionOpen('solver-opts', false) },
				el('summary', {}, el('span', {}, 'Advanced settings'), info('advanced')),
				box);
			fold.addEventListener('toggle', () => { state.sbSections['solver-opts'] = fold.open; });
			group.append(fold);
		}
	}

	sb.append(group);

	// No list of blocks below this. The panel used to carry every compartment,
	// transfer, parameter and expression in the model with an editable value
	// beside each, while the tree of the model was a second panel on the right:
	// a model of any size had its blocks in two places at once, in two orders,
	// in two panels competing for the width of the window. The tree is below
	// this now -- see `#sb-top` in index.html -- and a value is edited where the
	// block is opened, which is the settings dialog.

	sbRestore(caret);
	// The information panel, if it is open on one of these rows, says what
	// the row says now.
	refreshInfo();
}

// --- results ------------------------------------------------------------------

/**
 * What the Chart and the Table say about a model that computes nothing.
 *
 * A model with no compartments, no expressions and no parameters is not a
 * fault -- it is what a model looks like before anything has been added to it,
 * and it has to be possible to look at one without being told off. So the run
 * succeeds, produces the time grid and nothing else, and this says why the
 * chart is empty and where to go to change that.
 */
function nothingToShow(where) {
	const box = el('div', { className: 'empty-model' },
		el('b', {}, 'Nothing to show yet.'),
		el('span', {},
			`This model has no blocks that produce a value, so there is nothing to `
			+ `${where}. Add a compartment, an expression or a parameter and it `
			+ `appears here — a parameter is charted as the constant it is.`));
	const go = el('button', { className: 'primary', type: 'button' }, 'Go to Build');
	go.addEventListener('click', () => selectTab('build'));
	box.append(go);
	return box;
}

/**
 * The column behind one output.
 *
 * A run keeps only its states, and every other series is worked out from them
 * when something asks -- so a column is one of three things here. Cached: it
 * has been asked for before, and is kept, because scrolling a table must not
 * work a series out afresh per row. Constant: a parameter is its one value,
 * and travels as that rather than as a column of copies. Or not here yet: the
 * results live in the worker, and the series is asked of it -- batched with
 * whatever else this render wants, answered in one pass over the rows -- and
 * drawn when it arrives. Until then the column is `NaN` throughout, which a
 * chart draws as nothing and a table as a blank cell, rather than as a value
 * that was never true.
 *
 * With the results in this thread (no Worker, or `?mainthread`) there is no
 * waiting: the series is worked out on the spot.
 */
function column(r, i) {
	if (r.columns[i]) return r.columns[i];
	const o = r.outputs[i];
	if (o.constant != null) {
		r.columns[i] = new Float64Array(r.t.length).fill(o.constant);
		return r.columns[i];
	}
	if (r.local) {
		r.columns[i] = r.local.results.series(r.local.outputs[i]);
		return r.columns[i];
	}
	requestColumn(r, i);
	return pendingColumn(r);
}

/** One NaN column per result set, shared by everything still on its way. */
function pendingColumn(r) {
	if (!r.pending || r.pending.length !== r.t.length) {
		r.pending = new Float64Array(r.t.length).fill(NaN);
	}
	return r.pending;
}

/**
 * Asks the worker for a column, batching the asks of one render into one
 * message. The worker walks the rows once for the whole batch.
 */
let columnAsk = null;
function requestColumn(r, i) {
	// The worker that held these results is gone -- Stop terminates it, and
	// a worker that failed is replaced -- so nothing can answer. Said once,
	// and not remembered as asked, so a run that brings the results back can
	// be asked afresh.
	if (r.detached) {
		if (!r.saidDetached) {
			r.saidDetached = true;
			flash('Some series were not worked out before the run was stopped. Run again to see them.', 'warn');
		}
		return;
	}
	r.asked ??= new Set();
	if (r.asked.has(i)) return;
	r.asked.add(i);
	// A batch belongs to one result set. Two of them inside one microtask is
	// not something that happens today -- every caller renders from
	// `state.results` -- but the batch carries bare column *indices*, and an
	// index means a different series in a different run, so merging two would
	// file one set's columns onto the other's under the first one's run id.
	// The second one starts its own batch instead of joining this one.
	if (columnAsk && columnAsk.r !== r) sendColumnAsk();
	(columnAsk ??= { r, indices: [] }).indices.push(i);
	if (columnAsk.indices.length > 1) return;
	queueMicrotask(sendColumnAsk);
}

/** Posts whatever this render asked for, as one message. */
function sendColumnAsk() {
	{
		const ask = columnAsk;
		columnAsk = null;
		if (!ask) return;
		if (!resultsLive(ask.r) || ask.r.detached) {
			// Not asked after all. Unmarked rather than left marked: `asked` is
			// what stops the same column being requested twice, and a batch
			// that was dropped before it was sent would otherwise be asked for
			// never -- which is indistinguishable, from the outside, from a
			// column that is simply taking a long time.
			for (const i of ask.indices) ask.r.asked?.delete(i);
			return;
		}
		// Under the id of the run these results came from: see acceptResults.
		// To the worker that holds them, which for a scenario beside the
		// selected one is that scenario's own.
		(ask.r.worker ?? ensureWorker()).postMessage({ type: 'columns', id: ask.r.runId, indices: ask.indices });
	}
}

/** Whether these are results the page still shows: the selected scenario's, or one beside it. */
function resultsLive(r) {
	if (r === state.results) return true;
	for (const e of state.scenarioRuns.values()) if (e.r === r) return true;
	return false;
}

/** A scenario's worker answering for its columns: filed on its results, and drawn. */
function acceptScenarioColumns(entry, m) {
	const r = entry.r;
	if (!r || m.id !== r.runId) return;
	m.indices.forEach((i, k) => { r.columns[i] = m.columns[k]; });
	renderChart();
	renderTable();
	for (const done of r.onColumns ?? []) done();
	r.onColumns = [];
}

/** The worker's answer: filed, and whatever was waiting on it drawn again. */
function acceptColumns(m) {
	const r = state.results;
	if (!r || m.id !== r.runId) return;
	m.indices.forEach((i, k) => { r.columns[i] = m.columns[k]; });
	renderChart();
	renderTable();
	for (const done of r.onColumns ?? []) done();
	r.onColumns = [];
}

/**
 * Resolves once every one of these columns is here to be read.
 *
 * For an export, which needs the whole of what it writes: immediately when
 * they are cached or local, otherwise after the worker has answered.
 *
 * Asked for together when they are local, which is not a nicety. Everything
 * algebraic is worked out from `(t, y)` on request, and one evaluation covers
 * the whole algebraic vector however many values are read out of it -- so
 * `seriesMany` over forty thousand outputs is one pass over the rows and
 * `series` forty thousand times is forty thousand of them. On a landscape
 * model, where that vector is 200,000 values, the difference between those is
 * a few seconds and half an hour. The worker has always batched (see
 * `requestColumn`); a run on the main thread -- which is what the SciPy
 * solvers are -- did not.
 */
function ensureColumns(r, indices) {
	const missing = indices.filter((i) => !r.columns[i]);
	if (r.local && missing.length > 1) {
		const cols = r.local.results.seriesMany(missing.map((i) => r.local.outputs[i]));
		missing.forEach((i, k) => { r.columns[i] = cols[k]; });
		return Promise.resolve();
	}
	for (const i of missing) column(r, i);
	if (!missing.some((i) => !r.columns[i])) return Promise.resolve();
	return new Promise((resolve) => {
		(r.onColumns ??= []).push(() => {
			if (indices.every((i) => r.columns[i])) resolve();
			else (r.onColumns ??= []).push(() => resolve());
		});
	});
}

function pickDefaultSeries() {
	const outs = state.results?.outputs ?? [];
	if (!outs.length) return;
	const compartments = outs.map((o, i) => ({ o, i }))
		.filter(({ o }) => o.kind === 'compartment');
	let chosen;
	if (compartments.length && compartments.length <= DEFAULT_SERIES) {
		chosen = compartments.map(({ i }) => i);
	} else if (compartments.length) {
		const lastBlock = compartments[compartments.length - 1].o.block;
		chosen = compartments.filter(({ o }) => o.block === lastBlock).map(({ i }) => i);
	} else {
		// A parameter is a flat line: worth being able to put on a chart,
		// never worth being what the chart opens on -- unless it is all this
		// model has, which is the case of a model still being built.
		const computed = outs.map((o, i) => ({ o, i }))
			.filter(({ o }) => o.kind !== 'parameter');
		chosen = (computed.length ? computed : outs.map((o, i) => ({ o, i })))
			.map(({ i }) => i);
	}
	// One colour set, so a model that opens with a chart opens with eight
	// solid lines rather than thirty-two in four styles. The rest of the
	// capacity is there to be asked for.
	state.selected = chosen.slice(0, DEFAULT_SERIES);
}

/**
 * Whether what is on the chart belongs to the model that is on screen.
 *
 * Results carry the model revision they were computed from, so this is one
 * comparison. It matters because the alternative -- which is what this used to
 * do -- is a Chart tab showing curves from the last model that worked while
 * the current one has a broken equation in it, and nothing on the chart saying
 * so.
 */
function resultsAreStale() {
	return !!state.results && state.results.rev !== state.rev;
}

/**
 * Whether to show results at all.
 *
 * Stale results are hidden -- but not while a run is on its way, because with
 * auto-run on every keystroke's commit would blank the chart for a third of a
 * second and fill it again, and a chart that flickers on every edit is worse
 * than one that is briefly a third of a second behind. At rest, what is shown
 * is always this model's.
 */
function resultsShowable() {
	if (!state.results) return false;
	if (!resultsAreStale()) return true;
	return state.running || autoRunTimer !== null;
}

/**
 * Puts the chart and the table into the state the results are actually in.
 *
 * Called from every path that can change the answer: an edit, a run starting,
 * a run finishing, a run failing.
 */
function renderStaleness() {
	const show = resultsShowable();
	// A model that computes nothing has results that are perfectly current and
	// have nothing in them. The chart stays hidden either way, and the note
	// `renderChart` left in the shell is the one that explains it.
	const nothing = !!state.results && !state.results.outputs.length;
	// The distribution mode puts a different picture in the same space, so the
	// chart goes with it -- decided here, where every other reason to hide it
	// is decided, rather than by `renderChart` reaching past this.
	$('#chart').hidden = !show || nothing || showingSample();
	$('#legend').hidden = !state.results || (!show && !!state.results) || nothing
		|| showingSample();
	const table = $('#panel-table table');
	if (table) table.hidden = !show;

	for (const host of [$('.chart-shell'), $('#panel-table')]) {
		if (!host) continue;
		host.querySelector('.stale')?.remove();
		if (show || !state.results) continue;
		// One notice at a time: out-of-date beats empty, because it is the
		// reason nothing is on screen.
		host.querySelector('.empty-model')?.remove();
		host.append(staleNotice());
	}
}

/** Why the results are not on screen, and the way to make them current. */
function staleNotice() {
	const blocked = state.problems.length > 0;
	// Auto-run is on, and being held off by how long the last solve took.
	// Said out loud, because a chart that stops following the model with the
	// box still ticked reads as a program that has stopped working -- which
	// is what a first SciPy run, at two to twenty times the wall-clock of
	// the ones here, used to make it look like.
	const held = !blocked && !state.runProblem && state.autoRun && autoRunHeld();
	const box = el('div', { className: 'stale' },
		el('b', {}, blocked
			? 'These results are out of date, and the model will not run.'
			: 'These results are out of date.'),
		el('span', {}, blocked
			? 'The model has changed since they were computed, and something in '
				+ 'it has to be fixed before it can run again — see the strip '
				+ 'at the top.'
			: state.runProblem
				? 'The model has changed since they were computed, and the last '
					+ 'run failed — see the strip at the top.'
				: held
					? 'The model has changed since they were computed. The last '
						+ `solve took ${(state.lastSolveMs / 1000).toFixed(1)} s `
						+ `under ${solverLabel(state.lastSolveSolver)}, which is `
						+ 'long enough that re-running on every edit would get '
						+ 'in the way — so this one is waiting to be asked.'
					: 'The model has changed since they were computed. They are '
						+ 'not shown, because results that are not this model\u2019s '
						+ 'are worse than no results.'),
	);
	if (!blocked) {
		const go = el('button', { className: 'primary', type: 'button' }, 'Run');
		go.addEventListener('click', () => runSimulation({ manual: true }));
		box.append(go);
	}
	return box;
}

/**
 * Empties the chart pane and the table of everything that belonged to the
 * results just discarded: the filter, the picker, the legend, the unit note,
 * the table and whatever notice sat in the chart's place. What is left is one
 * line saying the results are on their way, which `renderChart` replaces when
 * they arrive.
 */
/**
 * The line that stands where a result is not yet, and the way to one.
 *
 * The chart and the table show the same thing, from here, because they used to
 * show different things: the chart said why nothing was happening and offered
 * the button, and the table showed an empty panel. Two places that mean the
 * same thing are two places to keep in step.
 */
/**
 * What produced what is on screen, on the Chart and the Table.
 *
 * A chart of five curves and a chart of five medians with their spread behind
 * them look alike from across a desk, and which of them it is changes what
 * every line on it means. The tabs were built when a run was one thing; there
 * are four kinds now -- nothing yet, a deterministic run, a probabilistic one,
 * and one realisation of a probabilistic one replayed -- and the reader has to
 * be able to see which without remembering what they last pressed.
 *
 * Said in the corner of each view rather than in a notice: it is a standing
 * fact about what is there, not news.
 */
function renderRunKind() {
	// What is drawn behind the lines, named for the line it is about: the two
	// centres do not share a spread, and the median's is not symmetric.
	const behind = (keys) => {
		if (state.chartSpread === 'bands') return ' with the percentile bands';
		if (state.chartSpread !== 'sem' && state.chartSpread !== 'sd') return ' on their own';
		const of = keys.filter((k) => k !== 'single');
		if (of.length > 1) return ' each with its own spread';
		if (of[0] === 'median') {
			return state.chartSpread === 'sem' ? ' with its own 95% interval'
				: ' with the middle 68% of them';
		}
		return state.chartSpread === 'sem' ? ' with ± 1.96 standard errors'
			: ' with ± one standard deviation';
	};
	// And which lines are through them. A list rather than a name, since any
	// combination can be up.
	const describeLines = () => {
		const keys = linesOn().map((l) => l.key);
		if (keys.length === 1 && keys[0] === 'single') {
			return 'held — the line is this model’s own single run';
		}
		const names = linesOn().map((l) => (l.key === 'single' ? 'this model’s own run' : `the ${l.name}`));
		const list = names.length === 1 ? names[0]
			: `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
		return `as ${list}${behind(keys)}`;
	};
	const r = state.results;
	const prob = currentProb();
	const words = [];
	/*
	  No result yet: this line says nothing at all. pendingResults() fills the
	  body of both views with that fact, and says why it is so and offers the
	  button. A line above it repeating the bare fact is the fact twice, the
	  first time without the one control that could act on it.
	*/
	if (!r) { /* the body speaks for this state */ }
	else if (r.replayed != null) {
		words.push(`Realisation ${(Number(r.replayed.index ?? r.replayed) + 1).toLocaleString()}`,
			'of the probabilistic run, integrated again on its own values');
	} else if (prob) {
		const drawn = state.chartMode === 'dist' ? 'as a distribution at one time'
			: state.chartMode === 'scatter' ? 'one against another, a point per realisation'
				: describeLines();
		words.push(`${prob.iterations.toLocaleString()} realisations`, drawn);
		if (prob.screen) words.push('over the categories kept');
		// The one case where a sample is not reported where a single run is.
		if (!sameTimes(prob.t, r.t)) {
			words.push(`on the model’s grid of ${prob.t.length.toLocaleString()} times, `
				+ 'since the solver’s own points differ in every realisation');
		}
	} else {
		const beside = shownScenarioRuns({ hidden: false });
		words.push(beside.length
			? `${beside.length + 1} scenarios, a deterministic run of each`
			: 'One deterministic run');
		if (r.outputs?.length) {
			words.push(`${r.outputs.length.toLocaleString()} series over `
				+ `${r.t.length.toLocaleString()} times`);
		}
	}
	// A preview is not an ordinary run and must not read as one: the model on
	// screen is not the model these numbers came from.
	if (r && state.preview) {
		words.push(`at ${state.preview.length} optimised value`
			+ `${state.preview.length === 1 ? '' : 's'} — the model still holds its own`);
	}
	// What else could be here, where something could. A probabilistic run is
	// the thing a reader does not know is possible until it is offered.
	if (r && !prob && ed.hasDistributions(state.raw)) {
		words.push('this model has distributions — Uncertainty → Probabilistic… draws the spread');
	}
	const text = words.join(' · ');
	for (const id of ['#chart-what', '#table-what']) {
		const node = $(id);
		if (node) node.textContent = text;
	}
	// And the way to be rid of it, which belongs beside the line that says it
	// is there.
	for (const id of ['#chart-discard', '#table-discard']) {
		const b = $(id);
		if (!b) continue;
		b.hidden = !prob;
		b.title = 'Throw the realisations away: the bands, the histograms and the '
			+ 'sensitivities go with them, and the memory they are held in is returned. '
			+ 'The model is not touched.';
	}
}

function pendingResults() {
	const p = el('p', { className: 'hint results-pending' },
		state.autoRun
			? 'No results for this model yet. They appear here when it has run.'
			: 'No results for this model yet. Auto-run is off, so nothing will '
				+ 'happen until you ask for it.');
	// With the switch off, nothing is coming on its own: the way to a result
	// belongs in the place that says there is none.
	if (!state.autoRun) {
		const go = el('button', { className: 'primary', type: 'button' }, 'Run');
		go.addEventListener('click', () => runSimulation({ manual: true }));
		p.append(' ', go);
	}
	return p;
}

function clearResultsViews() {
	$('#pick-filter')?.replaceChildren();
	$('#picker')?.replaceChildren();
	const info = $('#pickinfo');
	if (info) info.textContent = '';
	const legend = $('#legend');
	if (legend) { legend.hidden = true; legend.replaceChildren(); }
	const warn = $('#unitwarn');
	if (warn) warn.hidden = true;
	const shell = $('.chart-shell');
	if (shell) {
		shell.querySelector('.empty-model')?.remove();
		shell.querySelector('.stale')?.remove();
		shell.querySelector('.results-pending')?.remove();
		shell.append(pendingResults());
	}
	// The table says the same thing as the chart. It used to be emptied and
	// left blank, which reads as a program that has stopped rather than as a
	// model that has not been run -- and the way to a result was on the other
	// tab.
	const table = $('#table-body');
	if (table) table.replaceChildren(pendingResults());
	tableDirty = true;
	// And the footer's line, which is a view of the results like the rest of
	// these -- the one that was left behind when a model was replaced.
	clearStatus();
	renderRunKind();
	renderStaleness();
}

function renderResults() {
	// Nothing integrated yet. A probabilistic run lands here too, and it can
	// be the *first* thing a model is asked for -- press Probabilistic… on a
	// model that has never been run and this used to read `state.results.
	// outputs` of null and throw, which took the rest of the handler with it:
	// no bands, no statistics in the footer, and a chart still saying nothing
	// had run. The deterministic run that fills this in is started by
	// `acceptProbabilistic`; until it lands there is nothing to pick from.
	if (!state.results) {
		renderChart();
		renderTable();
		renderStaleness();
		return;
	}
	// Keep the user's picks across runs where the labels still exist.
	const labels = new Set(state.selected.map((i) => state.prevLabels?.[i]));
	if (state.prevLabels) {
		const remapped = [];
		state.results.outputs.forEach((o, i) => {
			if (labels.has(o.label) && remapped.length < MAX_SERIES) remapped.push(i);
		});
		state.selected = remapped.length ? remapped : [];
	}
	if (!state.selected.length) pickDefaultSeries();
	state.prevLabels = state.results.outputs.map((o) => o.label);
	// A band over a quantity that does not vary with time is a flat line saying
	// only that it is flat. Where *everything* selected is one of those -- three
	// sampled parameters and an expression over them, which is what somebody
	// exploring distributions writes first -- the distribution is the picture,
	// and it is the one the tab opens on.
	//
	// Once per probabilistic run, so a reader who then chooses `over time`
	// keeps it for the rest of that run.
	const prob = currentProb();
	if (prob && state.probModeFor !== prob.runId) {
		state.probModeFor = prob.runId;
		if (allConstant()) state.chartMode = 'dist';
	}

	renderPicker();
	renderChart();
	renderTable();
	// Last, because the table's panel is rebuilt wholesale and the notice
	// lives inside it.
	renderStaleness();
	if (state.tab === 'code') renderCode();
}

/**
 * Which outputs pass the chart's filter.
 *
 * A 2-D model runs to dozens of lines -- four nuclides across three landscape
 * objects in five compartments is sixty -- and picking eight of them out of a
 * wall of chips is the part that does not scale. The name pattern is the same
 * one the block search uses, wildcards and all, so there is one thing to learn
 * rather than two.
 */
function pickedOutputs() {
	const outs = state.results.outputs;
	// The rule itself is in ./chart.js, where it can be tested without a
	// browser -- see `filterOutputs` there for what it is and what it used to
	// get wrong. *Probabilistic* is a constraint only while there is a sample
	// for it to be about.
	const held = state.pick.sample ? sampleHolds() : null;
	return filterOutputs(outs, { ...state.pick, among: held?.labels ?? null },
		ed.nameMatcher(state.pick.query))
		.map((i) => ({ o: outs[i], i }));
}

function pickFiltering() {
	const f = state.pick;
	return !!f.query.trim() || f.kinds.size > 0
		|| [...f.indices.values()].some((s) => s.size > 0)
		|| (!!f.sample && !!sampleHolds());
}

/** The search box, the kind chips and one row of chips per index list. */
function renderPickFilter() {
	const host = $('#pick-filter');
	const active = document.activeElement;
	const keep = active && (active.id === 'pick-search' || active.id === 'pick-pop-search')
		&& host.contains(active);
	const keepId = keep ? active.id : null;
	const caret = keep ? [active.selectionStart, active.selectionEnd] : null;
	// Which chip had the focus, if one did. Every chip in here is destroyed
	// and rebuilt on each render, so clicking one moved the focus to the body
	// -- and the next Tab started again from the top of the page, in the
	// middle of narrowing a list of two thousand lines down to four.
	const focused = !keep && active && host.contains(active) ? chipKey(active) : null;
	// The search box is the one control here that outlives a render: it has
	// a completion list hanging off it, and a list anchored to a field that is
	// destroyed on every keystroke is a list that is never open. Everything
	// else is rebuilt around it.
	const input = pickSearchBox();
	for (const child of [...host.children]) if (child !== input) child.remove();
	if (input.parentNode !== host) host.prepend(input);

	const outs = state.results.outputs;
	const f = state.pick;
	if (input.value !== f.query) input.value = f.query;

	const chipRow = (label, chips) => el('div', { className: 'pick-filter-row' },
		el('span', { className: 'pick-filter-label' }, label),
		el('div', { className: 'search-kinds' }, chips));

	// Only what the sample holds -- the series the probabilistic run kept and
	// the parameters it varied, whose chips carry its mark -- the same chip
	// the block tree has. First, because after a sample it is the question
	// the rest are asked within.
	const held = sampleHolds();
	if (held) {
		const on = !!f.sample;
		const n = outs.filter((o) => held.labels.has(o.label)).length;
		const chip = el('button', {
			className: `search-chip search-chip-sample${on ? ' is-on' : ''}`, type: 'button',
			'aria-pressed': on ? 'true' : 'false',
			title: `Only the ${n.toLocaleString()} lines the probabilistic run has realisations `
				+ 'of: the series it kept and the parameters it varied.',
		}, sampleMark('kept'), `Probabilistic (${n.toLocaleString()})`);
		chip.dataset.chip = 'sample';
		chip.addEventListener('click', () => {
			f.sample = !on;
			state.pickChips = MAX_PICK_CHIPS;
			renderPicker();
		});
		host.append(chipRow('sample', [chip]));
	}

	// Kinds, in the order the outputs come in.
	const kinds = [...new Set(outs.map((o) => o.kind))];
	if (kinds.length > 1) {
		host.append(chipRow('kind', kinds.map((k) => {
			const on = f.kinds.has(k);
			const chip = el('button', {
				className: `search-chip${on ? ' is-on' : ''}`, type: 'button',
			// The same names the block list uses; `${k}s` turned
			// `index_operation` into `index_operations`, underscore and all.
			}, ed.KIND_LABEL[k] ?? `${k}s`);
			chip.dataset.chip = 'kind';
			chip.dataset.chipvalue = k;
			chip.addEventListener('click', () => {
				if (on) f.kinds.delete(k); else f.kinds.add(k);
				renderPicker();
			});
			return chip;
		})));
	}

	// One selector per index list any output carries -- per *group* of lists,
	// since a sub-set and the list it is cut from ask the same question -- and
	// the chips behind it, in a popover, for the indices that actually appear
	// in the results. They used to be drawn in the open, one row per list:
	// one assessment model in the corpus carries sixteen lists, one of them
	// 353 flow paths long, and the rows filled the panel below the fold before the
	// picker or the chart was reached. A selector says what is filtered and
	// by how much in three words; the chips are there when one is opened.
	const perList = new Map();
	for (const o of outs) {
		(o.dims ?? []).forEach((d, at) => {
			if (!perList.has(d)) perList.set(d, new Set());
			perList.get(d).add(o.index?.[at]);
		});
	}
	const groups = filterGroups(state.raw?.index_lists ?? [], perList.keys());
	f.groups = groups;
	const selectors = [];
	for (const [group, lists] of groups) {
		// The indices, in the order the outputs carry them, once each.
		const values = [];
		const seen = new Set();
		for (const list of lists) {
			for (const v of perList.get(list) ?? []) {
				if (!seen.has(v)) { seen.add(v); values.push(v); }
			}
		}
		// A list with one index is no choice to offer.
		if (values.length < 2) continue;
		if (!f.indices.has(group)) f.indices.set(group, new Set());
		const allowed = f.indices.get(group);
		const isOpen = state.pickOpen === group;
		const wrap = el('div', { className: `pick-group${isOpen ? ' is-open' : ''}` });
		const label = allowed.size === 0 ? group
			: allowed.size === 1 ? `${group} · ${[...allowed][0]}`
				: `${group} · ${allowed.size} of ${values.length}`;
		const button = el('button', {
			className: `pick-group-btn${allowed.size ? ' is-on' : ''}`, type: 'button',
			title: `${lists.length > 1
				? `${lists.join(', ')} share their indices, so they are filtered together. `
				: ''}${values.length} ${values.length === 1 ? 'index' : 'indices'} in the results`
				+ `${allowed.size ? `; ${allowed.size} chosen` : ''}.`,
			'aria-expanded': String(isOpen),
			'aria-haspopup': 'true',
		}, el('span', { className: 'pick-group-name' }, label),
		el('span', { className: 'pick-group-caret' }, '▾'));
		button.dataset.chip = 'group';
		button.dataset.chipvalue = group;
		button.addEventListener('click', () => {
			state.pickOpen = isOpen ? null : group;
			state.pickPopQuery = '';
			renderPickFilter();
		});
		wrap.append(button);
		if (isOpen) wrap.append(pickPopover(group, lists, values, allowed));
		selectors.push(wrap);
	}
	if (selectors.length) {
		host.append(el('div', { className: 'pick-filter-row' },
			el('span', { className: 'pick-filter-label' }, 'index'),
			el('div', { className: 'pick-groups' }, selectors)));
	}
	// A popover hangs from the left edge of its selector unless that would
	// run it off the right of the panel, in which case it hangs from the
	// right edge instead. Measured, since the selector's place is the
	// wrapping's to decide.
	const pop = host.querySelector('.pick-pop');
	if (pop) {
		const room = host.getBoundingClientRect().right;
		if (pop.getBoundingClientRect().right > room - 4) pop.classList.add('is-right');
	}
	installPickPopoverClosers();

	// Acting on what the filter found: the fastest way to chart "these four".
	const shown = pickedOutputs();
	const actions = el('div', { className: 'pick-filter-actions' });
	const showAll = el('button', {
		className: 'ghost', type: 'button',
		disabled: !shown.length,
		title: `Chart the first ${MAX_SERIES} of them`,
	}, `Show these (${Math.min(shown.length, MAX_SERIES)})`);
	showAll.addEventListener('click', () => {
		state.selected = shown.slice(0, MAX_SERIES).map(({ i }) => i);
		renderPicker();
		renderChart();
		renderTable();
	});
	const none = el('button', { className: 'ghost', type: 'button' }, 'Show none');
	none.addEventListener('click', () => {
		state.selected = [];
		renderPicker();
		renderChart();
		renderTable();
	});
	actions.append(showAll, none);
	if (pickFiltering()) {
		const clear = el('button', { className: 'ghost', type: 'button' }, 'Clear filter');
		clear.addEventListener('click', clearPickFilter);
		actions.append(clear);
	}
	host.append(actions);

	if (keep) {
		const back = keepId === 'pick-search' ? input : host.querySelector('#pick-pop-search');
		back?.focus();
		if (caret && back) back.setSelectionRange(caret[0], caret[1]);
	} else {
		focusChip(host, focused);
	}
}

function clearPickFilter() {
	state.pick.query = '';
	state.pick.kinds.clear();
	for (const s of state.pick.indices.values()) s.clear();
	state.pick.sample = false;
	renderPicker();
}

/**
 * The chart's search box, made once. It completes over the names in the run's
 * outputs -- the blocks and the indices the labels are made of -- so what
 * there is to find can be seen rather than remembered.
 */
let pickSearch = null;
function pickSearchBox() {
	if (pickSearch) return pickSearch;
	const input = el('input', {
		type: 'search', id: 'pick-search', className: 'search-input',
		value: '', spellcheck: false,
		placeholder: 'Find a line — try Soil, or *I-129*',
		title: 'Matches anywhere in the label. With * or ? it is a pattern over '
			+ 'the whole label: * any run of characters, ? exactly one. As you type '
			+ 'it lists the blocks and indices there are to find; Ctrl-Space or ↓ '
			+ 'lists them all.',
	});
	input.addEventListener('input', () => {
		state.pick.query = input.value;
		// A new filter is a new list, so it starts at the first page of chips.
		state.pickChips = MAX_PICK_CHIPS;
		renderPicker();
	});
	input.addEventListener('keydown', (e) => {
		// With the list open, Escape is the list's to close.
		if (e.key === 'Escape' && !completionIsOpen(input)) clearPickFilter();
	});
	attachCompletion(input, searchLook(() => state.results?.outputs ?? []));
	pickSearch = input;
	return input;
}

/** Past this many indices the popover gets a box to find one by. */
const PICK_POP_SEARCH_FROM = 12;

/**
 * The chips of one index group, under its selector.
 *
 * All the indices the results carry for these lists, each a chip that is on
 * or off; a search box when there are more than fit a glance, since 353 flow
 * paths is a list nobody scans; and All, None and a way out.
 */
function pickPopover(group, lists, values, allowed) {
	const pop = el('div', { className: 'pick-pop', role: 'dialog', 'aria-label': `${group} filter` });
	const head = el('div', { className: 'pick-pop-head' },
		el('b', {}, group),
		lists.length > 1
			? el('span', { className: 'pick-pop-also' },
				`also ${lists.filter((l) => l !== group).join(', ')}`)
			: null);
	const all = el('button', { className: 'ghost', type: 'button', title: 'Choose every index listed here' }, 'All');
	all.addEventListener('click', () => {
		for (const v of values) allowed.add(v);
		renderPicker();
	});
	const none = el('button', { className: 'ghost', type: 'button', title: 'Choose none: no constraint on this list' }, 'None');
	none.addEventListener('click', () => { allowed.clear(); renderPicker(); });
	const close = el('button', { className: 'ghost pick-pop-close', type: 'button', title: 'Close (Esc)' }, '×');
	close.addEventListener('click', () => { state.pickOpen = null; renderPickFilter(); });
	head.append(el('span', { className: 'spacer' }), all, none, close);
	pop.append(head);

	let shown = values;
	if (values.length > PICK_POP_SEARCH_FROM) {
		const q = state.pickPopQuery ?? '';
		const search = el('input', {
			type: 'search', className: 'search-input pick-pop-search', value: q,
			placeholder: `Find among ${values.length}`, spellcheck: false, id: 'pick-pop-search',
		});
		search.addEventListener('input', () => {
			state.pickPopQuery = search.value;
			renderPickFilter();
		});
		pop.append(search);
		const needle = q.trim().toLowerCase();
		if (needle) shown = values.filter((v) => String(v).toLowerCase().includes(needle));
	}
	const chips = el('div', { className: 'search-kinds pick-pop-chips' });
	for (const v of shown) {
		const on = allowed.has(v);
		const chip = el('button', { className: `search-chip${on ? ' is-on' : ''}`, type: 'button' }, v);
		chip.dataset.chip = group;
		chip.dataset.chipvalue = v;
		chip.addEventListener('click', () => {
			if (on) allowed.delete(v); else allowed.add(v);
			renderPicker();
		});
		chips.append(chip);
	}
	if (!shown.length) chips.append(el('span', { className: 'hint' }, 'Nothing matches.'));
	pop.append(chips);
	return pop;
}

/**
 * A popover closes on Escape and on a click anywhere outside it -- installed
 * once, on the document, since the popover itself is rebuilt on every render.
 */
let pickClosersInstalled = false;
function installPickPopoverClosers() {
	if (pickClosersInstalled) return;
	pickClosersInstalled = true;
	document.addEventListener('pointerdown', (ev) => {
		if (!state.pickOpen) return;
		if (ev.target.closest?.('.pick-group')) return;
		state.pickOpen = null;
		renderPickFilter();
	}, true);
	document.addEventListener('keydown', (ev) => {
		if (ev.key !== 'Escape' || !state.pickOpen) return;
		const was = state.pickOpen;
		state.pickOpen = null;
		renderPickFilter();
		// Back to the selector, so the keyboard is not dropped on the body.
		focusChip($('#pick-filter'), { chip: 'group', value: was });
	});
}

/**
 * How many chips the picker draws at once.
 *
 * A landscape model reports thousands of outputs -- one per block per nuclide
 * per landscape object -- and the picker drew a button for every one of them,
 * on every keystroke in the filter box above it. Nobody reads the two
 * thousandth chip: the filter is how a line is found in a list that long, and
 * the filter is what the typing is for.
 */
const MAX_PICK_CHIPS = 300;

function renderPicker() {
	renderPickFilter();
	const box = $('#picker');
	box.replaceChildren();
	const outs = state.results.outputs;
	const all = pickedOutputs();
	if (!outs.length) {
		box.append(el('p', { className: 'hint' },
			'This model has no blocks that produce a value yet.'));
	} else if (!all.length) {
		box.append(el('p', { className: 'hint' }, 'No output matches the filter.'));
	}
	// A chart line always has its chip, wherever it falls in the list: it is
	// the only way to switch it off again.
	const room = state.pickChips ?? MAX_PICK_CHIPS;
	const shown = all.length <= room
		? all
		: [
			...all.slice(0, room),
			...all.slice(room).filter(({ i }) => state.selected.includes(i)),
		];
	// Which lines the sample holds, so a chip says before it is clicked whether
	// it will draw a spread or a single curve.
	const held = sampleHolds()?.labels ?? null;
	shown.forEach(({ o, i }) => {
		const pos = state.selected.indexOf(i);
		const on = pos >= 0;
		const full = !on && state.selected.length >= MAX_SERIES;
		const which = held?.get(o.label) ?? null;
		const b = el('button', {
			className: `pick${which ? ` has-sample is-${which}` : ''}`, type: 'button', disabled: full,
			title: full
				? `A chart shows at most ${MAX_SERIES} series; clear one first.`
				: `${o.label}${o.unit ? ` (${o.unit})` : ''}`
					+ (which === 'varied' ? ' — varied by the probabilistic run'
						: which ? ' — kept by the probabilistic run' : ''),
		}, el('span', { className: 'series-swatch dot' }), o.label, which ? sampleMark(which) : null);
		b.setAttribute('aria-pressed', String(on));
		if (on) {
			const { color, set } = seriesStyle(pos);
			b.style.setProperty('--swatch', `var(--series-${color + 1})`);
			b.querySelector('.dot').dataset.set = String(set);
		}
		b.addEventListener('click', () => {
			const at = state.selected.indexOf(i);
			if (at >= 0) state.selected.splice(at, 1);
			else if (state.selected.length < MAX_SERIES) state.selected.push(i);
			renderPicker();
			renderChart();
			renderTable();
		});
		box.append(b);
	});
	if (all.length > shown.length || room > MAX_PICK_CHIPS) {
		const left = all.length - Math.min(room, all.length);
		const more = el('button', { className: 'ghost pick-more', type: 'button' },
			left ? `${left.toLocaleString()} more — show them` : 'Show fewer');
		more.addEventListener('click', () => {
			state.pickChips = left ? all.length : MAX_PICK_CHIPS;
			renderPicker();
		});
		box.append(more);
	}
	const filtered = pickFiltering() ? `, ${all.length} of ${outs.length} listed` : '';
	$('#pickinfo').textContent = state.selected.length >= MAX_SERIES
		? `${MAX_SERIES} lines charted (the maximum)${filtered}`
		: `${state.selected.length} of ${outs.length} charted${filtered}`;
}

/**
 * Whether every selected series is one that does not vary over time.
 *
 * Two ways to be one. A sampled *parameter* says so outright: `constant` comes
 * back with the run, because the worker knows -- a parameter's value is its
 * slot. And a quantity worked out from parameters alone -- `E = a + b*c`, which
 * is what somebody exploring three distributions writes first -- is flat
 * without being marked, so its own curve is asked. One pass over a column that
 * is already in hand.
 */
function allConstant() {
	const r = state.results;
	const outs = r?.outputs ?? [];
	const prob = currentProb();
	if (!state.selected.length || !r || !prob) return false;
	const at = new Map(prob.outputs.map((o, k) => [o.label, k]));
	const mid = prob.quantiles?.indexOf(0.5) ?? -1;
	const flat = (v) => {
		if (!v || v.length < 2) return false;
		for (let j = 1; j < v.length; j++) {
			// Not `===`: a value worked out afresh at every time can differ in
			// the last bit or two without varying in any sense a reader means.
			if (Math.abs(v[j] - v[0]) > Math.abs(v[0]) * 1e-12) return false;
		}
		return true;
	};
	return state.selected.every((i) => {
		if (outs[i]?.constant != null) return true;
		// The run's own median over time, which is in hand: the deterministic
		// column is fetched from the worker when something asks for it, and at
		// the moment this is decided it is still a placeholder.
		const k = at.get(outs[i]?.label);
		if (k === undefined || mid < 0) return false;
		// A varied parameter is one value per realisation, so it is flat by
		// what it is rather than by looking.
		if (prob.bands?.[k]?.flat) return true;
		return flat(prob.bands?.[k]?.q?.[mid]);
	});
}

/** Whether the Chart tab is showing distributions rather than curves. */
function showingDistribution() {
	return state.chartMode === 'dist' && !!currentProb();
}

/** Whether it is showing one output against another. */
function showingScatter() {
	return state.chartMode === 'scatter' && !!currentProb();
}

/** Either of the two pictures that replace the curves. */
function showingSample() {
	return showingDistribution() || showingScatter();
}

/**
 * Which series a scatter puts across the bottom.
 *
 * Held by label rather than by index, because a re-run renumbers the outputs
 * and an index would quietly become a different series. Falls back to the
 * first one selected, so the picture is never empty for want of a choice.
 */
function scatterXIndex() {
	const outs = state.results?.outputs ?? [];
	if (state.scatterX) {
		const at = outs.findIndex((o) => o.label === state.scatterX);
		if (at >= 0) return at;
	}
	return state.selected[0] ?? -1;
}

/**
 * Asks the worker for the realisations behind a scatter.
 *
 * Keyed like the histograms, and for the same reason: switching back to a
 * picture already drawn costs nothing, and a stale answer is never shown
 * beside a new selection.
 */
function askPoints() {
	const prob = currentProb();
	const r = state.results;
	if (!prob || !r) return;
	const labels = new Map(prob.outputs.map((o, k) => [o.label, k]));
	const xi = scatterXIndex();
	const xk = labels.get(r.outputs[xi]?.label);
	const ys = state.selected
		.filter((i) => i !== xi)
		.map((i) => labels.get(r.outputs[i]?.label))
		.filter((k) => k !== undefined)
		.slice(0, MOST_PANELS);
	const at = chartAtIndex();
	const key = `${prob.runId}|${at}|${xk}|${ys.join(',')}`;
	if (state.points?.key === key) return;
	if (xk === undefined || !ys.length) {
		state.points = { key, x: null, ys: [], at, asking: false };
		return;
	}
	state.points = { key, x: null, ys: null, at, asking: true };
	ensureWorker().postMessage({ type: 'prob-points', id: prob.runId, x: xk, ys, at });
}

function acceptPoints(m) {
	const prob = currentProb();
	if (!prob || m.id !== prob.runId) return;
	if (m.gone) {
		state.points = null;
		flash('The realisations are no longer held — run the model probabilistically again.', 'warn');
		renderChart();
		return;
	}
	if (!state.points) return;
	const named = (k, values) => ({
		label: prob.outputs[k]?.label ?? '',
		unit: prob.outputs[k]?.unit ?? '',
		values,
	});
	state.points = {
		...state.points,
		asking: false,
		of: m.of,
		x: named(m.x.index, m.x.values),
		// The colour a series has on the chart is the colour it keeps here.
		ys: m.ys.map((y, i) => ({ ...named(y.index, y.values), colour: i })),
	};
	renderChart();
	// The Table asks the same question for its own sake, so it is redrawn
	// here too rather than waiting for the next thing to touch it.
	if (state.tab === 'table') drawTable();
}

/** Which time the distribution is of, as an index into the output grid. */
/**
 * The times a *sample* is reported at, which are not always the run's.
 *
 * Every realisation has to be reported at the times every other realisation is
 * reported at, or there is no column to take a percentile down -- so a
 * probabilistic run is always on the model's grid. A run of a model that asks
 * for **the solver's own points** is not: it is reported at the steps that one
 * integration took. The two axes then differ in length and in value, and an
 * index into one means nothing in the other.
 *
 * Every picture *of the sample* -- the distribution, the scatter, the table at
 * one time -- is indexed against this one.
 */
function sampleTimes() {
	return currentProb()?.t ?? state.results?.t ?? null;
}

function chartAtIndex() {
	const n = sampleTimes()?.length ?? 0;
	if (!n) return 0;
	const at = state.chartAt;
	return at == null ? n - 1 : Math.min(n - 1, Math.max(0, at));
}

/** Whether two time axes are the same times, so nothing has to be moved. */
function sameTimes(a, b) {
	if (a === b) return true;
	if (!a || !b || a.length !== b.length) return false;
	for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
	return true;
}

/**
 * A curve on the sample's time axis, read onto the run's.
 *
 * Usually they are the same times and this is the identity. They are not when
 * the model asks for the solver's own points, or for those *and* a grid: the
 * run is reported at the steps it took and the sample at the grid, and the
 * chart plots `values[j]` at `t[j]` without anything checking that the two
 * came from the same axis. A band would be drawn against the wrong times, and
 * silently.
 *
 * Linear between the sample's own points -- which is what the chart draws
 * through them anyway, so this aligns the arrays and changes no picture.
 * Outside the sample's span there is nothing to say, and NaN is how the chart
 * is told so.
 */
function ontoAxis(from, to) {
	if (sameTimes(from, to)) return (v) => v;
	const idx = new Int32Array(to.length);
	const w = new Float64Array(to.length);
	let k = 0;
	for (let j = 0; j < to.length; j++) {
		const x = to[j];
		while (k + 1 < from.length && from[k + 1] < x) k++;
		idx[j] = k;
		const a = from[k];
		const b = from[Math.min(k + 1, from.length - 1)];
		w[j] = x < from[0] || x > from[from.length - 1] ? NaN : (b > a ? (x - a) / (b - a) : 0);
	}
	return (v) => {
		if (!v) return v;
		const out = new Float64Array(to.length);
		for (let j = 0; j < to.length; j++) {
			const i = idx[j];
			const a = v[i];
			const b = v[Math.min(i + 1, v.length - 1)];
			out[j] = a + (b - a) * w[j];
		}
		return out;
	};
}

/**
 * Asks the worker for the histograms the distribution mode draws.
 *
 * Keyed on what it is an answer to -- the run, the time, and which series --
 * so switching back to a mode already drawn costs nothing, and a stale answer
 * is never shown beside a new selection.
 */
function askHistograms() {
	const prob = currentProb();
	const r = state.results;
	if (!prob || !r) return;
	const labels = new Map(prob.outputs.map((o, k) => [o.label, k]));
	const wanted = state.selected
		.map((i) => ({ i, k: labels.get(r.outputs[i]?.label) }))
		.filter((x) => x.k !== undefined)
		.slice(0, MOST_PANELS);
	const at = chartAtIndex();
	// The bins are part of what this is an answer to: changing either of them
	// is a different histogram of the same column, and a key that left them
	// out would hand back the last one.
	const key = `${prob.runId}|${at}|${state.histBins ?? 'auto'}|${state.histScale}`
		+ `|${wanted.map((x) => x.k).join(',')}`;
	if (state.hist?.key === key) return;
	if (!wanted.length) { state.hist = { key, items: [], at, asking: false }; return; }
	state.hist = { key, items: null, at, asking: true };
	ensureWorker().postMessage({
		type: 'prob-hist', id: prob.runId, indices: wanted.map((x) => x.k), at,
		bins: state.histBins, scale: state.histScale,
	});
}

function acceptHistograms(m) {
	const prob = currentProb();
	if (!prob || m.id !== prob.runId) return;
	if (m.gone) {
		state.hist = null;
		flash('The realisations are no longer held — run the model probabilistically again.', 'warn');
		renderChart();
		return;
	}
	if (!state.hist) return;
	state.hist = {
		...state.hist,
		asking: false,
		of: m.of,
		items: m.items.map((it) => ({
			label: prob.outputs[it.index]?.label ?? '',
			unit: prob.outputs[it.index]?.unit ?? '',
			hist: it.histogram,
			summary: it.summary,
		})),
	};
	renderChart();
}

/**
 * What the Table can show over time, and which of those this model allows.
 *
 * `run` is there only where a deterministic run is, and `raw` only for a
 * single series: the matrix is time down and realisation across, so a second
 * series would want a second table rather than more columns.
 */
const TABLE_SERIES = [
	['median', 'the median of the realisations'],
	['mean', 'their mean'],
	['realisation', 'one realisation'],
	['run', 'this model’s own run'],
	['raw', 'every realisation'],
];

function tableSeriesOn() {
	const one = state.selected.length === 1;
	return TABLE_SERIES.filter(([k]) => (k === 'raw' ? one : true));
}

/** Which of them is in force, given what this model and this selection allow. */
function tableSeriesNow() {
	const can = new Set(tableSeriesOn().map(([k]) => k));
	return can.has(state.tableSeries) ? state.tableSeries : 'median';
}

/**
 * The control that chooses between the Chart tab's two pictures.
 *
 * Only there when there is something to choose: a distribution needs
 * realisations to be a distribution *of*, and with one deterministic run the
 * question does not arise.
 */
function renderChartMode() {
	const row = $('#chart-mode-row');
	const mode = $('#chart-mode');
	const at = $('#chart-at');
	if (!row || !mode || !at) return;
	const prob = currentProb();
	row.hidden = !prob || !state.results;
	if (row.hidden) return;
	mode.value = state.chartMode;
	mode.title = state.chartMode === 'dist'
		? 'The spread of each selected series at one time, as a histogram.'
		: state.chartMode === 'scatter'
			? 'The selected series against one of them, one point per realisation.'
			: 'Each selected series over time: the median of the realisations with '
				+ 'the spread drawn behind it.';
	// Which series goes across the bottom. Only a scatter has one, and it is
	// offered out of what is selected -- the picture is of the selection, and
	// an axis from outside it would be a series the reader cannot see.
	const xs = $('#chart-x');
	if (xs) {
		xs.hidden = state.chartMode !== 'scatter';
		if (!xs.hidden) {
			const outs = state.results.outputs;
			const want = scatterXIndex();
			xs.replaceChildren();
			for (const i of state.selected) {
				xs.append(el('option', { value: outs[i]?.label ?? '', selected: i === want },
					`x: ${outs[i]?.label ?? ''}`));
			}
			xs.title = 'Which series runs across the bottom. The rest of the selection '
				+ 'is plotted up the side against it.';
		}
	}
	// Which lines are drawn and what is behind them. Only in the time picture,
	// where there are lines to be about.
	const lines = $('#chart-lines');
	const spread = $('#chart-spread');
	const on = linesOn().map((l) => l.key);
	if (lines) {
		lines.hidden = state.chartMode !== 'time';
		for (const box of lines.querySelectorAll('input[data-line]')) {
			box.checked = on.includes(box.dataset.line);
			// The last one on cannot be turned off. A box that says so by
			// being fixed is better than a click that silently comes back.
			box.disabled = box.checked && on.length === 1;
		}
		lines.title = 'Which lines go through each band: the middle of the realisations, '
			+ 'their average, and the model integrated once at its own values. Any '
			+ 'combination — for a skewed output the median and the mean are far apart, '
			+ 'and how far is worth seeing.';
	}
	if (spread) {
		// Nothing to be behind: the model's own run is not of the sample, so
		// with it alone there is no spread to draw.
		spread.hidden = state.chartMode !== 'time' || !on.some((k) => k !== 'single');
		spread.value = state.chartSpread;
		// The two spreads are named for the line they are about, because they
		// *are* different numbers: the median's are order statistics off the
		// sorted realisations and are not symmetric about it, so a `±` on them
		// would be a small lie. See the band builder in `renderChart`.
		const of = on.filter((k) => k !== 'single');
		const BOTH = {
			sem: ['standard error of each line',
				'Each line with its own: the mean ± 1.96 standard errors, and the median’s '
				+ '95% interval read off the sorted realisations.'],
			sd: ['spread of each line',
				'Each line with its own: the mean ± one standard deviation, and the middle '
				+ '68% of the realisations about the median.'],
		};
		const MEDIAN = {
			sem: ['standard error of the median',
				'The median’s own 95% interval, read off the sorted realisations: how well '
				+ 'the middle itself is known, which narrows as the sample grows. Lopsided '
				+ 'for a skewed output, because the realisations are.'],
			sd: ['middle 68% of realisations',
				'Where the realisations are, the median’s version of ± one standard '
				+ 'deviation: the middle 68% of them, which does not narrow however many '
				+ 'are run.'],
		};
		const MEAN = {
			sem: ['± standard error',
				'The mean ± 1.96 standard errors: how well the average itself is known, '
				+ 'which narrows as the sample grows.'],
			sd: ['± standard deviation',
				'The mean ± one standard deviation: where the realisations are, which does '
				+ 'not narrow however many are run.'],
		};
		const spreads = of.length > 1 ? BOTH : of[0] === 'median' ? MEDIAN : MEAN;
		for (const [value, [text]] of Object.entries(spreads)) {
			const opt = spread.querySelector(`option[value="${value}"]`);
			if (opt && opt.textContent !== text) opt.textContent = text;
		}
		spread.title = spreads[state.chartSpread]?.[1]
			?? 'The percentile pairs the run was asked for, outermost faintest.';
	}
	// How the distribution is binned. Only that picture has bins.
	const binRow = $('#chart-bins-row');
	if (binRow) {
		binRow.hidden = state.chartMode !== 'dist';
		if (!binRow.hidden) {
			const count = $('#chart-bins');
			const how = $('#chart-binscale');
			if (count && document.activeElement !== count) {
				count.value = state.histBins == null ? '' : String(state.histBins);
			}
			if (count) {
				count.title = 'How many bins each distribution is counted into. Empty is '
					+ 'the rule: Sturges’ for a panel of its own, and a finer count for '
					+ 'the shared axis, where outlines over one another read as curves.';
			}
			if (how) {
				how.value = state.histScale;
				how.title = state.histScale === 'log'
					? 'The bin edges are spaced by the logarithm of the value — the honest '
						+ 'picture of a sample that spans decades, which on even spacing is '
						+ 'one tall bin and a tail nobody can see. A sample reaching zero '
						+ 'cannot be binned this way and is left evenly spaced.'
					: state.histScale === 'linear'
						? 'The bin edges are evenly spaced, whatever the sample spans.'
						: 'Evenly spaced, unless the sample spans more than two decades and '
							+ 'is positive throughout, which is binned by the logarithm.';
			}
		}
	}
	at.hidden = state.chartMode === 'time';
	if (at.hidden) return;
	// The *sample's* times: this index is sent to the worker, which reads it
	// against the realisations' own axis.
	const t = sampleTimes();
	const want = chartAtIndex();
	// Rebuilt only when the grid under it changed, so the list is not thrown
	// away and remade on every redraw of the chart.
	if (at.dataset.len !== String(t.length)) {
		at.replaceChildren();
		for (let j = 0; j < t.length; j++) {
			at.append(el('option', { value: String(j) },
				`${fmtTime(t[j])} ${state.raw.simulation?.time_unit ?? 'year'}`));
		}
		at.dataset.len = String(t.length);
	}
	at.value = String(want);
}

function renderChart() {
	const r = state.results;
	const shell = $('.chart-shell');
	shell.querySelector('.empty-model')?.remove();
	shell.querySelector('.results-pending')?.remove();
	// Whether the chart element is on screen is `renderStaleness`'s decision
	// and nobody else's -- it is the one place that knows whether what is in
	// it belongs to the model on screen. What belongs here is what goes in the
	// space instead, and not asking the chart to autoscale over no data at
	// all, which would draw a pair of axes from NaN to NaN.
	shell.querySelector('.hist-view')?.remove();
	// Nothing integrated. `clearResultsViews` has already put the "no results
	// yet" line in the shell; there is nothing here to draw over it, and
	// reading `outputs` of null is what made a probabilistic run on a model
	// that had never been run take the whole handler down with it.
	if (!r) {
		renderChartMode();
		renderRunKind();
		return;
	}
	if (!r.outputs.length) {
		$('#legend').hidden = true;
		$('#unitwarn').hidden = true;
		shell.append(nothingToShow('chart'));
		renderChartMode();
		return;
	}
	// One output against another, realisation by realisation.
	if (showingScatter()) {
		$('#legend').hidden = true;
		$('#unitwarn').hidden = true;
		askPoints();
		const box = el('div', { className: 'hist-view' });
		shell.append(box);
		const held = state.points;
		if (!held || held.asking || !held.ys) {
			box.append(el('p', { className: 'hint' }, 'Working out the points…'));
		} else {
			const when = `${fmtTime(sampleTimes()?.[held.at])} `
				+ `${state.raw.simulation?.time_unit ?? 'year'}`;
			renderScatter(box, {
				x: held.x,
				ys: held.ys,
				when,
				of: held.of ?? currentProb().iterations,
				arrange: state.histArrange,
				fit: state.scatterFit,
				more: Math.max(0, state.selected.length - 1 - held.ys.length),
				onArrange: (how) => { state.histArrange = how; renderChart(); },
				onFit: (on) => { state.scatterFit = on; renderChart(); },
			});
		}
		renderChartMode();
		renderRunKind();
		renderStaleness();
		return;
	}
	// The other picture over the same selection: what the realisations came to
	// at one instant, rather than where they went over time.
	if (showingDistribution()) {
		$('#legend').hidden = true;
		$('#unitwarn').hidden = true;
		askHistograms();
		const box = el('div', { className: 'hist-view' });
		shell.append(box);
		const held = state.hist;
		if (!held || held.asking || !held.items) {
			box.append(el('p', { className: 'hint' }, 'Working out the distributions…'));
		} else {
			const when = `${fmtTime(sampleTimes()?.[held.at])} `
				+ `${state.raw.simulation?.time_unit ?? 'year'}`;
			renderHistograms(box, {
				items: held.items,
				when,
				of: held.of ?? currentProb().iterations,
				more: Math.max(0, state.selected.length - held.items.length),
				arrange: state.histArrange,
				onArrange: (how) => { state.histArrange = how; renderChart(); },
				bins: state.histBins,
				scale: state.histScale,
			});
		}
		renderChartMode();
		renderRunKind();
		renderStaleness();
		return;
	}
	// A probabilistic result replaces the line with its median and the spread
	// it came from: the 5-95 band behind a 25-75 one, so the chart says both
	// "where most of them were" and "where nearly all of them were". Matched to
	// the deterministic outputs by label, because the probabilistic run kept
	// only the series it was asked for and the chart's selection is over all of
	// them.
	const prob = currentProb();
	const probAt = prob
		? new Map(prob.outputs.map((o, k) => [o.label, k]))
		: null;
	// Which lines go through each band. Any combination of the three, so the
	// two that are far apart for a skewed output can be compared where they
	// are rather than one after the other.
	//
	// They wear the *output's* colour and are told apart by their pattern:
	// colour is which series this is, the pattern is which line of it. On its
	// own a line takes the style its position gives it, because there is then
	// nothing for a pattern to distinguish.
	const lines = prob ? linesOn() : [CHART_LINES[2]];
	const many = lines.length > 1;
	// The sample is on the model's grid; the run under it may be on the steps
	// its solver took. See `ontoAxis`.
	const onRun = prob ? ontoAxis(prob.t, r.t) : ((v) => v);
	const series = state.selected.flatMap((i, pos) => {
		const label = r.outputs[i].label;
		const own = { label, values: column(r, i), unit: r.outputs[i].unit, slot: pos };
		const k = probAt?.get(label);
		if (k === undefined) return [own];
		const band = bandOf(prob, k);
		const q = prob.quantiles;
		const at = (p2) => onRun(band.q[q.indexOf(p2)]);
		const mean = onRun(band.mean);
		const med = band.med && {
			errLo: onRun(band.med.errLo), errHi: onRun(band.med.errHi),
			bodyLo: onRun(band.med.bodyLo), bodyHi: onRun(band.med.bodyHi),
		};
		// What goes behind one line. The model's own run never carries a
		// spread: a band over the realisations with a line from a different
		// run through it is two pictures overlaid.
		//
		// `first` is whether this is the first line of the sample on this
		// series. The percentile bands are a property of the sample and not of
		// any line through it, so they are painted once -- twice would be the
		// same fill at twice the opacity.
		const spreadFor = (kind, first) => {
			if (kind === 'single') return null;
			if (state.chartSpread === 'bands') {
				if (!first) return null;
				// Whatever pairs the run was asked for, outermost faintest: the
				// default is 5–95 behind 25–75, and a model may say otherwise.
				const pairList = bandPairs(q);
				return pairList.map(([lo, hi], j) => ({
					lo: at(lo), hi: at(hi), alpha: 0.11 + (0.1 * (j + 1)) / Math.max(1, pairList.length),
				}));
			}
			if (state.chartSpread !== 'sem' && state.chartSpread !== 'sd') return null;
			// Each line's own. *How well is it known* and *where are the
			// realisations* are the same two questions of either centre, but
			// the answers are different numbers, and a shaded region drawn
			// about the mean with the median running through it is an interval
			// around something the line is not.
			//
			// For the mean they are the textbook two. The median has neither
			// in closed form, so its pair is read off the sorted realisations
			// instead -- `medianSpread` in the worker -- and comes out
			// lopsided for a skewed output, which is right.
			if (kind === 'median') {
				const m = med;
				if (!m) return null;
				return state.chartSpread === 'sem'
					? [{ lo: m.errLo, hi: m.errHi, alpha: 0.2 }]
					: [{ lo: m.bodyLo, hi: m.bodyHi, alpha: 0.2 }];
			}
			const sd = onRun(band.sd?.sd);
			const n = onRun(band.sd?.n);
			if (!sd || !mean) return null;
			const lo = new Float64Array(sd.length);
			const hi = new Float64Array(sd.length);
			for (let j = 0; j < sd.length; j++) {
				// 1.96 standard errors is the 95% interval for a mean; one
				// standard deviation is drawn as it is, since it is not an
				// interval and saying 1.96 of it would imply one.
				const half = state.chartSpread === 'sem'
					? (1.959964 * sd[j]) / Math.sqrt(Math.max(1, n?.[j] ?? 1))
					: sd[j];
				lo[j] = mean[j] - half;
				hi[j] = mean[j] + half;
			}
			return [{ lo, hi, alpha: 0.2 }];
		};
		let drawn = 0;
		return lines.map((line) => {
			const first = line.key !== 'single' && drawn++ === 0;
			return {
				...own,
				label: many ? `${label} (${line.name})` : label,
				set: many ? line.set : undefined,
				values: line.key === 'single' ? own.values
					: line.key === 'mean' ? mean
						: (q.includes(0.5) ? at(0.5) : own.values),
				bands: spreadFor(line.key, first),
			};
		});
	});
	// The scenarios run beside the selected one: every selected output again,
	// once per scenario, matched by label -- a scenario is the same model and
	// reports the same outputs -- and read onto this run's times, which they
	// share unless the model reports the solver's own steps. See withScenarios
	// in ./scenarios.js for how the lines share the colours.
	const beside = chartScenarioRuns();
	const runOrder = scenariosToRun(state.raw, state.scenarioChoice);
	const activeName = ed.activeScenario(state.raw);
	let dropped = 0;
	let drawnSeries = series;
	if (beside.length || (chartScenarioRuns({ hidden: false }).length
		&& state.hiddenScenarios.has(activeName))) {
		const others = beside.map((e) => {
			const byLabel = new Map(e.r.outputs.map((o, j) => [o.label, j]));
			const onto = ontoAxis(e.r.t, r.t);
			return {
				name: e.name,
				at: Math.max(1, runOrder.indexOf(e.name)),
				lines: state.selected.map((i, pos) => {
					const j = byLabel.get(r.outputs[i].label);
					if (j === undefined) return null;
					const col = column(e.r, j);
					return {
						pos, label: r.outputs[i].label, unit: e.r.outputs[j].unit,
						// Still on its way: left as the NaN it is rather than
						// read onto another axis, which would make it a new
						// array nothing recognises as waiting.
						values: col === e.r.pending ? col : onto(col),
					};
				}).filter(Boolean),
			};
		});
		({ series: drawnSeries, dropped } = withScenarios(
			state.hiddenScenarios.has(activeName) ? [] : series, {
				active: activeName, others, outputs: state.selected.length,
				perOutput: lines.length, max: MAX_SERIES,
			}));
	}
	const pendingCols = new Set([r.pending, ...beside.map((e) => e.r.pending)]);
	const units = new Set(drawnSeries.map((s) => s.unit).filter(Boolean));
	const yLabel = units.size === 1 ? [...units][0] : '';
	const notes = [];
	if (dropped) {
		notes.push(`${dropped} scenario line${dropped === 1 ? '' : 's'} left out: a chart holds `
			+ `${MAX_SERIES}. Select fewer outputs, or hide a scenario in the legend.`);
	}
	if (units.size > 1) {
		notes.push(`Mixed units on one axis (${[...units].join(', ')}) — `
			+ 'values are not comparable.');
	}
	// A log axis cannot place a value that is not positive, so the chart drops
	// it -- and a series with nothing positive in it draws nothing at all,
	// which with a lit chip beside it reads as a fault in the program. Worth
	// saying now that a constant can be charted: a rate of zero is an ordinary
	// thing for a model to carry, and its line is not missing, just unplottable
	// on this axis.
	if (state.yLog) {
		const anyPositive = (v) => {
			for (let i = 0; i < v.length; i++) if (v[i] > 0) return true;
			return false;
		};
		// A series still on its way from the worker is NaN throughout, which
		// is not the same as zero throughout; it gets its note, if it earns
		// one, when it arrives.
		const nothing = drawnSeries.filter((s) => !pendingCols.has(s.values) && !anyPositive(s.values));
		if (nothing.length) {
			notes.push(nothing.length === 1
				? `${nothing[0].label} is zero or negative throughout, which a `
					+ 'log axis cannot draw — untick log value to see it.'
				: `${nothing.length} of these are zero or negative throughout, `
					+ 'which a log axis cannot draw — untick log value to see them.');
		}
	}
	renderChartMode();
	renderRunKind();
	$('#unitwarn').hidden = !notes.length;
	$('#unitwarn').textContent = notes.join(' ');
	chart.setScales({ xLog: state.xLog, yLog: state.yLog });
	chart.setData(r.t, drawnSeries, {
		xLabel: `Time (${state.raw.simulation?.time_unit ?? 'year'})`, yLabel,
	});
	// Coming back from one of the other two pictures, the chart's container
	// was `display: none` and had no size at all -- so the canvas was last
	// painted against a box of nothing and comes back as a handful of enormous
	// pixels. The observer answers a *change* of size and the element is
	// already the size it was before it was hidden, so nothing tells it to
	// paint again. One frame later the layout has settled and it can.
	requestAnimationFrame(() => { if (!$('#chart').hidden) chart?.draw(); });

	const lg = $('#legend');
	lg.replaceChildren();
	const toggles = scenarioToggles();
	lg.hidden = drawnSeries.length < 2 && !prob?.screen && !toggles;
	if (toggles) lg.append(toggles);
	// What the bands are over, when it is not every realisation: a band drawn
	// over the categories somebody chose to keep has to say so where the band
	// is, or it reads as the run.
	if (prob?.screen) {
		lg.append(el('span', { className: 'legend-item legend-screen' },
			`${prob.screen.kept.toLocaleString()} of ${prob.iterations.toLocaleString()} realisations `
			+ 'shown (categories)'));
	}
	drawnSeries.forEach((s, i) => {
		const { color, set } = styleOf(s, i);
		const swatch = el('span', { className: 'series-swatch legend-swatch' });
		// Both channels, because past the eighth line the hue alone is
		// ambiguous: the pattern is what tells the sets apart.
		swatch.dataset.set = String(set);
		swatch.style.setProperty('--swatch', `var(--series-${color + 1})`);
		lg.append(el('span', { className: 'legend-item' }, swatch, s.label));
	});
}

/**
 * The legend's switches for the scenarios, when more than one is on the
 * chart: one per scenario run, pressed while its lines are drawn. The table
 * follows them, so the two say the same thing.
 */
function scenarioToggles() {
	if (!state.results) return null;
	const all = chartScenarioRuns({ hidden: false });
	if (!all.length) return null;
	const names = [ed.activeScenario(state.raw), ...all.map((e) => e.name)];
	const box = el('span', { className: 'legend-scenarios' },
		el('span', { className: 'legend-scenarios-label' }, 'Scenarios'));
	for (const name of names) {
		const on = !state.hiddenScenarios.has(name);
		const b = el('button', {
			type: 'button', className: `search-chip legend-scenario${on ? ' is-on' : ''}`,
			title: on ? `Hide the lines of ${name}` : `Show the lines of ${name}`,
		}, name);
		b.setAttribute('aria-pressed', String(on));
		b.addEventListener('click', () => {
			if (on) state.hiddenScenarios.add(name); else state.hiddenScenarios.delete(name);
			renderChart();
			renderTable();
		});
		box.append(b);
	}
	return box;
}

/**
 * The columns of a table or an export over the scenarios: each output's
 * column in the selected scenario, then in each scenario beside it, read onto
 * the selected one's times. With no scenario beside it, the columns as they
 * were, under their own names.
 *
 * @param {number[]} idx  outputs of the selected scenario's run
 * @param {{hidden?: boolean}} [opts]  leave out the scenarios switched off in
 *   the legend, as the table does; an export writes every one
 * @returns {Array<{label: string, unit: string, output: object, values: () => ArrayLike<number>,
 *   r: object, i: number}>}
 */
function scenarioColumns(idx, { hidden = true } = {}) {
	const r = state.results;
	const beside = shownScenarioRuns({ hidden });
	const active = ed.activeScenario(state.raw);
	const showActive = !(hidden && beside.length && state.hiddenScenarios.has(active));
	const named = beside.length > 0;
	const lookups = beside.map((e) => ({
		e, byLabel: new Map(e.r.outputs.map((o, j) => [o.label, j])), onto: ontoAxis(e.r.t, r.t),
	}));
	const out = [];
	for (const i of idx) {
		const o = r.outputs[i];
		if (showActive || !named) {
			out.push({
				label: named ? scenarioLabel(o.label, active) : o.label, unit: o.unit ?? '',
				output: o, r, i, scenario: named ? active : null, values: () => column(r, i),
			});
		}
		for (const { e, byLabel, onto } of lookups) {
			const j = byLabel.get(o.label);
			if (j === undefined) continue;
			out.push({
				label: scenarioLabel(o.label, e.name), unit: e.r.outputs[j].unit ?? '',
				output: e.r.outputs[j], r: e.r, i: j, scenario: e.name,
				values: () => {
					const col = column(e.r, j);
					return col === e.r.pending ? col : onto(col);
				},
			});
		}
	}
	return out;
}

/**
 * How many rows of the table are built at once.
 *
 * A run may hold a hundred thousand output times, and a table of them is a
 * hundred thousand `<tr>` with a cell per column: several hundred thousand
 * elements, which takes seconds to build and a few hundred megabytes to hold.
 * Nobody reads the eighty-thousandth row -- what the table is for is looking
 * at the numbers, and what the whole run is for is the CSV export, which
 * streams and is not bounded by this.
 */
const TABLE_ROWS = 2000;

/**
 * Whether the table on screen matches the results.
 *
 * The table used to be rebuilt on every run and on every change of the picked
 * series, whether or not its tab was the one in front -- so the cost above was
 * paid by people who never opened it. Now a change marks it out of date and
 * `selectTab` builds it when it is actually going to be looked at.
 */
let tableDirty = true;

/**
 * The realisations at one time, one row each.
 *
 * The chart's distribution says what the spread *looks* like; this is the same
 * numbers, which is what somebody pasting them into a report needs. A summary
 * line first, because with a thousand rows underneath it the answer to "what
 * is the 95th percentile" should not be arrived at by counting.
 */
/** How many realisations the raw matrix puts on screen before asking. */
const TABLE_COLS = 25;

/**
 * One realisation of each selected series, over time, out of the sample.
 *
 * Fetched rather than held: the page keeps the bands and the worker keeps the
 * realisations. Keyed on what it is an answer to -- the run, the realisation
 * and the series -- so going back to one already read costs nothing, and a
 * stale answer is never drawn under a new selection.
 *
 * Returns null while there is nothing yet, which is the caller's cue to say
 * so rather than to draw an empty table.
 */
function sampleRows() {
	const prob = currentProb();
	const r = state.results;
	if (!prob || !r) return null;
	const labels = new Map(prob.outputs.map((o, k) => [o.label, k]));
	const want = state.selected
		.map((i) => labels.get(r.outputs[i]?.label))
		.filter((k) => k !== undefined);
	const key = `${prob.runId}|${state.tableReal}|${want.join(',')}`;
	if (state.tableCols?.key === key) return state.tableCols.asking ? null : state.tableCols;
	state.tableCols = { key, cols: new Map(), asking: true };
	askProbMatrices(want, String(state.tableReal)).then((m) => {
		// Another question has been asked since; this answer is about a
		// selection nobody is looking at.
		if (state.tableCols?.key !== key) return;
		const cols = new Map();
		if (m) m.indices.forEach((k, j) => cols.set(k, m.matrices[j]));
		else flash('The realisations are no longer held — run the model probabilistically again.', 'warn');
		state.tableCols = { key, cols, asking: false };
		tableDirty = true;
		drawTable();
	});
	return null;
}

/**
 * The whole matrix for one series: time down, realisation across.
 *
 * One series at a time, because a second would want a second table rather
 * than more columns -- every column here is already a realisation.
 *
 * Both directions are capped on screen and both say what they are hiding: a
 * thousand realisations over four hundred times is four hundred thousand
 * cells, which is not a table anybody reads and is enough DOM to stop the
 * page. The whole of it goes out through the results archive, which writes
 * every realisation of every kept series.
 */
function drawRawTable(wrap, out) {
	const prob = currentProb();
	const k = prob?.outputs.findIndex((o) => o.label === out?.label) ?? -1;
	if (!prob || k < 0) {
		wrap.append(el('p', { className: 'hint' },
			'The probabilistic run did not keep realisations of this series — see '
			+ 'Choose blocks… in the Probabilistic dialog.'));
		return;
	}
	const key = `${prob.runId}|raw|${k}`;
	if (state.tableRaw?.key !== key) {
		state.tableRaw = { key, asking: true, values: null, iterations: 0 };
		askProbMatrices([k], 'all').then((m) => {
			if (state.tableRaw?.key !== key) return;
			if (!m) {
				state.tableRaw = { key, asking: false, values: null, iterations: 0 };
				flash('The realisations are no longer held — run the model probabilistically again.', 'warn');
			} else {
				state.tableRaw = {
					key, asking: false, values: m.matrices[0], iterations: m.iterations,
				};
			}
			tableDirty = true;
			drawTable();
		});
	}
	const held = state.tableRaw;
	if (held.asking) {
		wrap.append(el('p', { className: 'hint' }, 'Reading every realisation…'));
		return;
	}
	if (!held.values) {
		wrap.append(el('p', { className: 'hint' }, 'Those realisations are no longer held.'));
		return;
	}
	const times = prob.t;
	const iterations = held.iterations;
	const rows = Math.min(times.length, state.tableRows ?? TABLE_ROWS);
	const cols = Math.min(iterations, state.tableRawCols ?? TABLE_COLS);
	const table = el('table');
	table.append(el('thead', {}, el('tr', {},
		el('th', {}, `Time (${state.raw.simulation?.time_unit ?? 'year'})`),
		...Array.from({ length: cols }, (_, i) => el('th', {}, `#${(i + 1).toLocaleString()}`)))));
	const body = el('tbody');
	for (let j = 0; j < rows; j++) {
		const at = j * iterations;
		body.append(el('tr', {},
			el('td', {}, fmtValue(times[j])),
			...Array.from({ length: cols }, (_, i) => el('td', {}, fmtValue(held.values[at + i])))));
	}
	table.append(body);
	wrap.append(table);
	const note = el('p', { className: 'hint table-hint' },
		`${out.label}${out.unit ? ` (${out.unit})` : ''}: `
		+ `${iterations.toLocaleString()} realisations over ${times.length.toLocaleString()} times. `
		+ `Showing ${cols.toLocaleString()} of them over `
		+ `${rows.toLocaleString()} times. `);
	if (cols < iterations) {
		const more = el('button', { className: 'ghost', type: 'button' },
			`Show ${Math.min(iterations - cols, TABLE_COLS).toLocaleString()} more realisations`);
		more.addEventListener('click', () => {
			state.tableRawCols = cols + TABLE_COLS;
			tableDirty = true;
			drawTable();
		});
		note.append(more, ' ');
	}
	if (rows < times.length) {
		const more = el('button', { className: 'ghost', type: 'button' },
			`Show ${Math.min(times.length - rows, TABLE_ROWS).toLocaleString()} more times`);
		more.addEventListener('click', () => {
			state.tableRows = rows + TABLE_ROWS;
			tableDirty = true;
			drawTable();
		});
		note.append(more, ' ');
	}
	note.append('The whole of it, for every kept series, goes out through '
		+ 'Save → Model with results.');
	wrap.append(note);
}

function drawSampleTable(wrap, outs) {
	const held = state.points;
	// It rides on the scatter's own question, which fetches exactly this: the
	// columns unsorted and paired by realisation.
	askSampleColumns();
	if (!held || held.asking || !held.ys) {
		wrap.append(el('p', { className: 'hint' }, 'Working out the realisations…'));
		return;
	}
	const cols = [held.x, ...held.ys].filter(Boolean);
	if (!cols.length) {
		wrap.append(el('p', { className: 'hint' },
			'None of the selected series was kept by the probabilistic run.'));
		return;
	}
	const when = `${fmtTime(sampleTimes()?.[held.at])} `
		+ `${state.raw.simulation?.time_unit ?? 'year'}`;
	wrap.append(el('p', { className: 'hint' },
		`One row per realisation, at ${when}. `
		+ `${(held.of ?? cols[0].values.length).toLocaleString()} were run`
		+ (cols[0].values.length !== held.of
			? `; ${cols[0].values.length.toLocaleString()} are listed — the rest were `
				+ 'screened out by the categories.' : '.')));

	const table = el('table');
	table.append(el('thead', {}, el('tr', {},
		el('th', {}, 'Realisation'),
		...cols.map((c) => el('th', {}, c.unit ? `${c.label} (${c.unit})` : c.label)))));
	// The summary above the rows, from the sorted copy of each column: a
	// thousand numbers are not read, they are looked up.
	const sorted = cols.map((c) => Float64Array.from(c.values).sort());
	const pctl = (v, p) => {
		if (!v.length) return NaN;
		const k = (v.length - 1) * p;
		const lo = Math.floor(k);
		const hi = Math.ceil(k);
		return lo === hi ? v[lo] : v[lo] + (v[hi] - v[lo]) * (k - lo);
	};
	const stat = (name, fn) => el('tr', { className: 'table-stat' },
		el('td', {}, name), ...sorted.map((v) => el('td', {}, fmtValue(fn(v)))));
	const body = el('tbody');
	body.append(stat('mean', (v) => v.reduce((a, b) => a + b, 0) / (v.length || 1)));
	body.append(stat('median', (v) => pctl(v, 0.5)));
	body.append(stat('5%', (v) => pctl(v, 0.05)));
	body.append(stat('95%', (v) => pctl(v, 0.95)));
	const rows = Math.min(cols[0].values.length, state.tableRows ?? TABLE_ROWS);
	for (let i = 0; i < rows; i++) {
		body.append(el('tr', {},
			el('td', {}, String(i + 1)),
			...cols.map((c) => el('td', {}, fmtValue(c.values[i])))));
	}
	table.append(body);
	wrap.append(table);
	if (rows < cols[0].values.length) {
		const left = cols[0].values.length - rows;
		const more = el('button', { className: 'ghost', type: 'button' },
			`Show ${Math.min(left, TABLE_ROWS).toLocaleString()} more`);
		more.addEventListener('click', () => { state.tableRows = rows + TABLE_ROWS; drawTable(); });
		wrap.append(more);
	}
}

/**
 * The same question the scatter asks, asked for the table's own sake.
 *
 * Every selected series against itself, so the table lists all of them rather
 * than all but the one the scatter is using as its x axis.
 */
function askSampleColumns() {
	const prob = currentProb();
	const r = state.results;
	if (!prob || !r) return;
	const labels = new Map(prob.outputs.map((o, k) => [o.label, k]));
	const ks = state.selected
		.map((i) => labels.get(r.outputs[i]?.label))
		.filter((k) => k !== undefined)
		.slice(0, MOST_PANELS);
	if (!ks.length) return;
	const at = chartAtIndex();
	const key = `${prob.runId}|${at}|${ks[0]}|${ks.slice(1).join(',')}`;
	if (state.points?.key === key) return;
	state.points = { key, x: null, ys: null, at, asking: true };
	ensureWorker().postMessage({
		type: 'prob-points', id: prob.runId, x: ks[0], ys: ks.slice(1), at,
	});
}

/** The Table's own mode control, which only a sample gives it a choice about. */
function renderTableMode() {
	const row = $('#table-mode-row');
	const mode = $('#table-mode');
	const at = $('#table-at');
	if (!row || !mode || !at) return;
	row.hidden = !currentProb() || !state.results;
	if (row.hidden) return;
	mode.value = state.tableMode;
	// Which run the rows are, over time.
	const which = $('#table-series');
	const real = $('#table-real');
	const now = tableSeriesNow();
	if (which) {
		which.hidden = state.tableMode !== 'time';
		if (!which.hidden) {
			const offer = tableSeriesOn();
			const key = offer.map(([k]) => k).join(',');
			if (which.dataset.keys !== key) {
				which.replaceChildren();
				for (const [value, label] of offer) which.append(el('option', { value }, label));
				which.dataset.keys = key;
			}
			which.value = now;
			which.title = 'What the rows are. A table of numbers cannot say which run it '
				+ 'is by looking, and after a sample there are several honest answers. '
				+ '*Every realisation* is the whole matrix — time down, realisation '
				+ 'across — and is offered one series at a time.';
		}
	}
	if (real) {
		real.hidden = state.tableMode !== 'time' || now !== 'realisation';
		if (!real.hidden) {
			real.max = String(currentProb().iterations);
			if (document.activeElement !== real) real.value = String(state.tableReal + 1);
			real.title = `Which of the ${currentProb().iterations.toLocaleString()} `
				+ 'realisations, as it was integrated during the run. Replaying one under '
				+ 'Analyse ▾ integrates it again and gives every series of it; this reads '
				+ 'the one already held.';
		}
	}
	at.hidden = state.tableMode !== 'at';
	if (at.hidden) return;
	// The sample's, as in the chart: the index goes to the worker.
	const t = sampleTimes();
	if (at.dataset.len !== String(t.length)) {
		at.replaceChildren();
		for (let j = 0; j < t.length; j++) {
			at.append(el('option', { value: String(j) },
				`${fmtTime(t[j])} ${state.raw.simulation?.time_unit ?? 'year'}`));
		}
		at.dataset.len = String(t.length);
	}
	at.value = String(chartAtIndex());
}

function renderTable() {
	tableDirty = true;
	// New results, or a different set of columns: back to the first page.
	state.tableRows = TABLE_ROWS;
	if (state.tab === 'table') drawTable();
}

function drawTable() {
	tableDirty = false;
	renderTableMode();
	const r = state.results;
	// The panel's own body, not the panel: the line above it says what kind of
	// run this is a table of, and that is written once rather than rebuilt with
	// every cell.
	const wrap = $('#table-body');
	wrap.replaceChildren();
	// Switching to the tab before anything has run: the same line the chart
	// shows, rather than a stack trace from reading `outputs` of nothing.
	if (!r) {
		wrap.append(pendingResults());
		return;
	}
	if (!r.outputs.length) {
		wrap.append(nothingToShow('tabulate'));
		return;
	}
	if (!state.selected.length) {
		wrap.append(el('div', { className: 'empty' },
			'Select one or more outputs to tabulate — the picker above the chart '
			+ 'decides what appears here.'));
		return;
	}
	const outs = state.selected.map((i) => r.outputs[i]);
	// The realisations at one time rather than one run over every time: the
	// same question the chart's distribution answers as a picture, answered
	// here as numbers a reader can copy.
	if (state.tableMode === 'at' && currentProb()) {
		drawSampleTable(wrap, outs);
		return;
	}
	// Which run these rows are. With no sample there is only one answer and
	// the control is not shown; with one, the reader has said.
	const prob = currentProb();
	const which = prob ? tableSeriesNow() : 'run';
	// The whole matrix is a table of its own -- time down, realisation across.
	if (which === 'raw') { drawRawTable(wrap, outs[0]); return; }
	// Read from the sample where that is what is asked for, and from the
	// deterministic run otherwise. A sample is on the model's grid and a run
	// may not be, so the times come from whichever this is.
	const fetched = which === 'realisation' ? sampleRows() : null;
	if (which === 'realisation' && !fetched) {
		wrap.append(el('p', { className: 'hint' }, 'Reading that realisation…'));
		return;
	}
	const probAt = prob ? new Map(prob.outputs.map((o, k) => [o.label, k])) : null;
	const fromSample = (i, k) => {
		if (k === undefined) return null;
		if (which === 'mean') return bandOf(prob, k).mean;
		if (which === 'median') {
			const j = prob.quantiles.indexOf(0.5);
			return j < 0 ? null : bandOf(prob, k).q[j];
		}
		return fetched?.cols?.get(k) ?? null;
	};
	const cols = state.selected.map((i, pos) => {
		if (which === 'run') return column(r, i);
		const got = fromSample(i, probAt?.get(outs[pos].label));
		// A series the run did not keep has no realisations to report, and a
		// blank column says that better than the deterministic curve would,
		// which would silently be a different thing from its neighbours.
		return got ?? new Float64Array(0);
	});
	const times = which === 'run' ? r.t : (prob?.t ?? r.t);
	const table = el('table');
	// Which columns the sample holds, marked as the chart's chips and the
	// tree mark them: whichever run the rows are of, these are the ones the
	// other readings of the sample can show.
	const held = sampleHolds()?.labels ?? null;
	// The deterministic runs, with a column per output per scenario where
	// scenarios are run beside the selected one -- grouped by output, so the
	// numbers to compare are side by side.
	const byScenario = which === 'run' && shownScenarioRuns({ hidden: false }).length
		? scenarioColumns(state.selected) : null;
	const heads = byScenario
		? byScenario.map((c) => el('th', {}, c.unit ? `${c.label} (${c.unit})` : c.label))
		: outs.map((o) => {
			const mark = held?.get(o.label) ?? null;
			return el('th', mark ? {
				className: `has-sample is-${mark}`,
				title: mark === 'varied' ? 'Varied by the probabilistic run' : 'Kept by the probabilistic run',
			} : {}, o.unit ? `${o.label} (${o.unit})` : o.label, mark ? sampleMark(mark) : null);
		});
	const shown = byScenario ? byScenario.map((c) => c.values()) : cols;
	table.append(el('thead', {}, el('tr', {},
		el('th', {}, `Time (${state.raw.simulation?.time_unit ?? 'year'})`), ...heads)));
	const body = el('tbody');
	const rows = Math.min(times.length, state.tableRows ?? TABLE_ROWS);
	for (let i = 0; i < rows; i++) {
		body.append(el('tr', {},
			el('td', {}, fmtValue(times[i])),
			...shown.map((c) => el('td', {}, i < c.length ? fmtValue(c[i]) : '—'))));
	}
	table.append(body);
	wrap.append(table);
	if (byScenario && byScenario.some((c) => c.r !== r) && shownScenarioRuns({ hidden: false })
		.some((e) => !sameTimes(e.r.t, r.t))) {
		wrap.append(el('p', { className: 'hint table-hint' },
			'The scenarios took their own solver steps, so theirs are read onto these times '
			+ 'along a straight line between their own points.'));
	}
	if (cols.some((c) => !c.length)) {
		wrap.append(el('p', { className: 'hint table-hint' },
			'A dash is a series the run did not keep realisations of — see '
			+ 'Choose blocks… in the Probabilistic dialog.'));
	}
	if (rows < times.length) {
		const left = times.length - rows;
		const more = el('button', { className: 'ghost', type: 'button' },
			`Show ${Math.min(left, TABLE_ROWS).toLocaleString()} more`);
		more.addEventListener('click', () => {
			state.tableRows = rows + TABLE_ROWS;
			drawTable();
		});
		wrap.append(el('p', { className: 'hint table-hint' },
			`Showing the first ${rows.toLocaleString()} of `
			+ `${times.length.toLocaleString()} times. Right-click the table to `
			+ `export all of them as CSV. `, more));
	} else {
		wrap.append(el('p', { className: 'hint table-hint' },
			'Right-click the table to export it as CSV.'));
	}
}

/**
 * Which half of the Generated tab is showing, and the last check's report.
 *
 * The report is kept on the module rather than in `state` because it is about
 * the *built system* rather than about the model or a run: it survives a run,
 * and it is thrown away by an edit, which `state.rev` already tracks.
 */
const generated = {
	view: 'code',
	// The picture and the check are asked for separately: the pattern is
	// structural and costs the build, the check costs an evaluation of the
	// whole model per colour group and per sampled column.
	pattern: null,
	check: null,
	rev: -1,
	model: null,
	busy: null,        // 'pattern' | 'check' | null
	progress: 0,
};

/** The Derivative code / Jacobian switch. */
function showGeneratedView(which) {
	generated.view = which === 'jacobian' ? 'jacobian' : 'code';
	for (const b of document.querySelectorAll('[data-codeview]')) {
		const on = b.dataset.codeview === generated.view;
		b.classList.toggle('is-on', on);
		b.setAttribute('aria-pressed', String(on));
	}
	$('#codeview').hidden = generated.view !== 'code';
	$('#jacview').hidden = generated.view !== 'jacobian';
	$('#codehint').textContent = generated.view === 'jacobian'
		? 'The matrix df/dy the stiff solvers are handed, and whether it is the '
			+ 'derivative of the code beside it.'
		: 'The derivative function generated from this model\u2019s equations, '
			+ 'compiled by the JavaScript engine before the solve.';
	if (generated.view === 'jacobian') renderJacobian();
}

/** Asks the worker for one of the two; the reply names which it is. */
function askJacobian(what) {
	if (generated.busy) return;
	if (state.running) { flash('A run is already going. Stop it first.', 'warn'); return; }
	generated.busy = what;
	generated.progress = 0;
	renderJacobian();
	const w = ensureWorker();
	state.runId = (state.runId ?? 0) + 1;
	w.postMessage({
		type: what === 'check' ? 'jacobian-check' : 'jacobian-pattern',
		id: state.runId,
		rev: state.rev,
		project: structuredClone(state.raw),
	});
}

function acceptJacobianPattern(m) {
	generated.busy = null;
	generated.pattern = m.report;
	generated.check = null;
	generated.rev = state.rev;
	generated.model = state.raw;
	if (state.tab === 'code' && generated.view === 'jacobian') renderJacobian();
	if (!m.report.available) flash('This model has no analytic Jacobian.', 'warn');
}

function acceptJacobianCheck(m) {
	generated.busy = null;
	generated.check = m.report;
	if (m.report.available) generated.pattern = m.report;
	generated.rev = state.rev;
	generated.model = state.raw;
	if (state.tab === 'code' && generated.view === 'jacobian') renderJacobian();
	const r = m.report;
	if (!r.available) { flash('This model has no analytic Jacobian.', 'warn'); return; }
	const said = {
		agrees: 'Jacobian check: every resolvable entry agrees with finite differences.',
		differs: `Jacobian check: ${r.disagreements} entr`
			+ `${r.disagreements === 1 ? 'y differs' : 'ies differ'} from finite differences.`,
		missing: `Jacobian check: the pattern is missing ${r.missing} entr`
			+ `${r.missing === 1 ? 'y' : 'ies'} the model has.`,
		colouring: 'Jacobian check: the colouring is not a colouring.',
	}[r.verdict];
	flash(said, r.verdict === 'agrees' ? 'ok' : 'warn');
}

/**
 * Every canvas repainted, because a canvas is pixels and not styles.
 *
 * Everything else on the page follows the theme for free: the stylesheet
 * redefines its custom properties and the browser repaints. A canvas does not
 * -- it keeps whatever was painted into it, in whatever colours were read at
 * the time -- so each one has to be told. Two things change the theme, the
 * button and the system's own setting, and both come through here so that
 * neither can be the one somebody forgets.
 */
function themeChanged() {
	chart?.draw();
	if (state.tab === 'code' && generated.view === 'jacobian') renderJacobian();
}

function renderJacobian() {
	// An edit invalidates both, and so does a different model: the matrix is
	// generated from the equations. The model itself is compared as well as
	// the counter, the way `matrixBuilt` does -- two ways of asking the same
	// question, and the cheaper one catches a file that arrives without
	// touching the counter.
	if (generated.rev !== state.rev || generated.model !== state.raw) {
		generated.pattern = null;
		generated.check = null;
	}
	// Opening the view draws the picture without being asked. It is the cheap
	// half -- structural, no differencing -- and a view that showed a button
	// where a drawing could be is a view that makes you ask for what you came
	// to look at.
	if (!generated.pattern && !generated.busy) askJacobian('pattern');
	renderJacobianView($('#jacview'), {
		pattern: generated.pattern,
		check: generated.check,
		stats: state.results?.stats ?? null,
		busy: generated.busy,
		progress: generated.progress,
		onCheck: () => askJacobian('check'),
		onDraw: () => askJacobian('pattern'),
	});
}

function renderCode() {
	const pre = $('#codeview');
	if (!state.results) {
		pre.textContent = 'Run the model to see the derivative function generated '
			+ 'from its equations.';
		return;
	}
	const src = state.results.generatedSource;
	// Three passes, in the order they run. The derivative is only the last of
	// them: what reads neither the clock nor the state is worked out once when
	// the model is built, what reads only the clock once per instant, and the
	// rest on every call. Showing only `dydt` would hide most of the model --
	// on a large assessment, all but a couple of hundred slots of it.
	const parts = [];
	if (src.invariant && /X\[/.test(src.invariant)) {
		parts.push(
			'// ===== worked out once, when the model is built ==================',
			'// Neither the clock nor the state reaches these, so they are left in',
			'// place for the whole run.',
			src.invariant,
			'',
		);
	}
	if (src.atInstant && /X\[/.test(src.atInstant)) {
		parts.push(
			'// ===== worked out once per instant ===============================',
			'// These move with the clock and nothing else, and a stiff solver asks',
			'// for the derivative several times at one instant -- every Newton',
			'// iteration of a step, every colour of a differenced Jacobian.',
			src.atInstant,
			'',
		);
	}
	parts.push(
		'// ===== dy/dt, on every call ======================================',
		src.dydt,
	);
	if (src.jacobian) {
		const rows = state.results.jacobian?.budgetRows;
		parts.push(
			'',
			'// ===== J * v, the Jacobian by forward-mode differentiation =======',
			'// Seeded once per colour group, which is how the whole of df/dy is',
			'// recovered in a handful of passes instead of one per state.',
			...(rows === 'diagonal' ? [
				'// The mass-balance audit\'s budget rows are left at their diagonal:',
				'// nothing reads a budget, and a Newton iteration needs no more.',
			] : rows === 'exact' ? [
				'// The mass-balance audit\'s budget rows are generated whole: this',
				'// solver puts the matrix into its formula, or colours it itself.',
			] : []),
			src.jacobian,
		);
	} else if (state.results.jacobian?.reason) {
		parts.push('', `// No analytic Jacobian: ${state.results.jacobian.reason}.`,
			'// df/dy is differenced instead.');
	}
	pre.textContent = parts.join('\n');
}

// --- files ---------------------------------------------------------------------

/**
 * Which blocks a run keeps: the model's endpoints.
 *
 * The usual answer to "which of these three thousand blocks did I want?"
 * is its endpoint list, which this tool reads out of the file. The dialog
 * opens on that list when the model came with one, and what is chosen is saved
 * back to the model -- so the next run keeps the same, and the list travels
 * with the project file. Choosing only: writing any of it to a file is Save….
 */
async function openEndpoints(onSaved = null) {
	const r = state.results;
	// Without a run there is still a list: what a run *would* report is a
	// function of the layout, and the layout exists as soon as the model
	// builds. Which is the case this dialog is most for -- the point of
	// choosing endpoints is to say what a run should keep *before* it keeps
	// everything, and a model whose full result is 2.8 GB is exactly the model
	// nobody wants to run twice to find that out.
	const outputs = outputsNow();
	if (!outputs?.length) {
		flash('The blocks to choose from come from the model, and this one will not '
			+ 'build — the strip above says what is wrong.', 'warn');
		return;
	}
	try {
		const { openEndpointPicker } = await import('./endpoints.js');
		openEndpointPicker({
			// Never a parameter: a probabilistic run keeps the ones it varies
			// whatever this says, and the rest are one number in every
			// realisation. See `canBeEndpoint`.
			outputs: outputs.filter((o) => ed.canBeEndpoint(o.kind)),
			// No run, no output grid: the picker says the rate rather than
			// pricing a file nobody is writing yet.
			times: r ? r.t.length : 0,
			endpoints: ed.endpoints(state.raw),
			// What the table is showing, as the fallback for a model that came
			// with no list of its own.
			shown: r ? [...new Set(state.selected.map((i) => r.outputs[i]?.block).filter(Boolean))] : [],
			onRemember: (names) => {
				// The same blocks are not an edit, in whatever order. Compared
				// with what the model's list comes to rather than with the
				// file's, which may still name parameters -- and writing it
				// back only to drop those would put a dot on Save for a Done
				// that changed nothing.
				const was = new Set(ed.endpoints(state.raw));
				const same = names.length === was.size && names.every((n) => was.has(n));
				if (!same && ed.setEndpoints(state.raw, names)) {
					// Saved with the model and undoable, but not a reason to
					// re-run: which series are written changes no number.
					modelChanged({ layoutOnly: true });
				}
				// Told to whatever opened this, so a dialog underneath can
				// show the new count rather than the one it opened with.
				onSaved?.();
			},
		});
	} catch (e) {
		flash(`Could not open the endpoint picker: ${e.message}`, 'warn');
	}
}

/**
 * Asks first when an export is larger than a tab can hold.
 *
 * Every export is built in memory before the browser is handed it, so the
 * question is not patience but capacity. A run of model G has
 * 831,314 series over 356 times: 2.8 GB of numbers, reached after half an hour
 * of solving, and found out about only at the end. The count of numbers is the
 * floor -- CSV is several times that, being text.
 *
 * @returns {boolean} whether to go ahead
 */
function confirmHugeExport(series, times) {
	const bytes = series * times * 8;
	if (bytes <= HUGE_EXPORT) return true;
	const go = window.confirm(
		`${series.toLocaleString()} series over ${times.toLocaleString()} times is about `
		+ `${(bytes / 1073741824).toFixed(1)} GB of numbers. That is more than this tab can `
		+ 'usually hold, and it has to be built in memory before it can be saved. Export it '
		+ 'anyway?\n\nShowing fewer lines and exporting the table is the way to a file that '
		+ 'will open.',
	);
	if (!go) flash('Did not export.', 'info');
	return go;
}

/**
 * Hands the browser a file. `body` is text or bytes; a Blob takes either.
 *
 * The URL is revoked on a timer rather than on the line after `click()`.
 * Chrome starts the download synchronously out of the click and does not mind
 * either way; not every browser does, and a URL revoked before the download
 * has picked it up gives a file that fails with nothing to say. `picture.js`
 * has always waited; this is the same wait, in one place, so the two cannot
 * drift again.
 */
const REVOKE_AFTER = 10000;

function download(name, body, type) {
	const blob = new Blob([body], { type });
	const url = URL.createObjectURL(blob);
	const a = el('a', { href: url, download: name });
	document.body.append(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER);
}

/**
 * The model's data out, as a spreadsheet or as an HDF5 tree.
 *
 * Every parameter and every lookup table, with whatever distribution each
 * carries -- not only the distributed half, so the file that comes out is one
 * this can read back as a complete picture rather than as a patch.
 *
 * With `handoff` the HDF5 tree goes to the HDF5 Browser rather than the disk,
 * as the results do; see `deliver`.
 */
async function exportData(as, keys = null, handoff = null) {
	const want = keys ? new Set(keys) : null;
	const nameOf = (row) => (row.block
		? (row.block.system ? `${row.block.system}.${row.block.name}` : row.block.name)
		: row.id);
	const rows = dt.collect(state.raw).filter((row) => !want || want.has(nameOf(row)));
	if (!rows.length) {
		handoff?.cancel();
		flash('This model has no parameters or lookup tables to write out.', 'warn');
		return;
	}
	const base = slug(state.raw.name);
	let where = '';
	try {
		if (as === 'xlsx') {
			const bytes = await writeDataWorkbook(rows, { name: base.slice(0, 31) || 'data' });
			download(`${base}-data.xlsx`, bytes,
				'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
		} else {
			const bytes = writeDataHDF5(rows, { root: state.raw.name || 'model' });
			({ where } = await deliver(bytes, `${base}-data.h5`, handoff));
		}
	} catch (e) {
		handoff?.cancel();
		showError({ name: e.name ?? 'Error', message: e.message, blockName: null });
		flash(`The data could not be written: ${e.message}`, 'warn');
		return;
	}
	const tables = new Set(rows.filter((r) => r.time != null).map((r) => r.id)).size;
	flash(`${rows.length.toLocaleString()} rows written`
		+ (tables ? `, including ${tables.toLocaleString()} lookup tables` : '') + `${where}.`, 'info');
}

/**
 * The other direction: what would the inputs have to be.
 *
 * The endpoints are offered from what a run *would* report -- `outputsNow()`,
 * from the layout alone -- so this needs no run to be set up. The variables
 * come from the worker, which is the only thing that can enumerate the
 * parameter slots of a built system.
 */
async function openOptimise() {
	if (state.problems.length) {
		showError({
			name: 'Optimise',
			message: 'This model does not build, so it cannot be run — and every '
				+ 'evaluation of an optimisation is a run.',
		});
		flash('Fix the problems above first.', 'warn');
		return;
	}
	const outs = outputsNow() ?? [];
	if (!outs.length) { flash('This model reports nothing to aim at.', 'warn'); return; }
	let variables;
	try {
		variables = await askVariables();
	} catch (e) {
		showError({
			name: 'Optimise',
			message: e.message,
			hint: 'An optimisation needs a model that builds, since every evaluation of '
				+ 'one is a run of it.',
		});
		return;
	}
	if (!variables.length) {
		flash('This model has no parameters to vary.', 'warn');
		return;
	}
	// A block, not a series, would be wrong here: a target is one number, so
	// the endpoints are offered one series at a time.
	const outputs = outs.map((o) => ({
		key: o.label, name: o.label, kind: o.kind ?? '', unit: o.unit ?? '',
		count: 1, system: o.block?.includes('.') ? o.block.slice(0, o.block.lastIndexOf('.')) : '',
	}));
	const vars = variables.map((v) => ({
		key: v.key, name: v.key, kind: 'parameter', unit: v.unit ?? '',
		count: 1, value: v.value,
		system: v.name.includes('.') ? v.name.slice(0, v.name.lastIndexOf('.')) : '',
	}));
	const times = Array.from(state.results?.t ?? timesOfModel());
	state.optOpen = openOptimiseDialog({
		outputs,
		variables: vars,
		times,
		setup: state.optSetup,
		onChange: (setup) => { state.optSetup = setup; },
		onRun: (setup) => {
			state.optSetup = setup;
			state.optId += 1;
			ensureWorker().postMessage({
				type: 'optimise',
				id: state.optId,
				project: projectNow(),
				targets: setup.targets,
				variables: setup.variables,
				method: setup.method,
				maxEvals: setup.maxEvals,
				seed: 1,
			});
		},
		onStop: () => cancelSimulation(),
		onTry: (values) => runAtValues(values, { keep: false }),
		onApply: (values) => runAtValues(values, { keep: true }),
	});
}

/**
 * The model as a message, built now rather than when it last ran.
 *
 * `state.project` is set by `runSimulation` and is null until something has
 * run -- so reading it here asked a question of a model that may never have
 * existed, and an optimisation is exactly the thing somebody reaches for
 * *before* running anything. Built from `state.raw` each time, which is also
 * the only way an edit made since the last run is the one that gets optimised.
 */
function projectNow() {
	return new Project(structuredClone(state.raw)).toJSON();
}

/** The parameter slots a built system has, which only the worker knows. */
function askVariables() {
	return new Promise((resolve, reject) => {
		const id = ++state.optId;
		variablesWaiting = { id, resolve, reject };
		ensureWorker().postMessage({ type: 'variables', id, project: projectNow() });
		setTimeout(() => {
			if (variablesWaiting?.id === id) {
				variablesWaiting = null;
				reject(new Error('The worker did not answer.'));
			}
		}, 30000);
	});
}

let variablesWaiting = null;

function acceptVariables(m) {
	const wait = variablesWaiting;
	if (!wait || m.id !== wait.id) return;
	variablesWaiting = null;
	if (m.ok) wait.resolve(m.variables);
	else wait.reject(new Error(m.message ?? 'The variables could not be worked out.'));
}

/**
 * `name[i][j]` back into the block and index it names.
 *
 * The spelling the sampler, the sensitivity and the optimiser all use for one
 * parameter slot. Null where this model has no such block.
 */
function slotOf(raw, key) {
	const m = /^([^[]+)((?:\[[^\]]*\])*)$/.exec(String(key ?? ''));
	if (!m) return null;
	const name = m[1];
	const found = findBlock(raw, name);
	if (!found) return null;
	const lists = found.block.index_lists ?? [];
	const index = {};
	[...m[2].matchAll(/\[([^\]]*)\]/g)].map((x) => x[1])
		.forEach((value, i) => { if (lists[i]) index[lists[i]] = value; });
	return { name, block: found.block, index };
}

/** Writes a set of `{key, value}` into a model, in place. */
function putValues(raw, values) {
	let n = 0;
	for (const v of values) {
		const at = slotOf(raw, v.key);
		if (!at) continue;
		try {
			if (Object.keys(at.index).length) {
				ed.setEntryValue(raw, at.name, at.index, 'value', String(v.value));
			} else {
				at.block.value = String(v.value);
			}
			n += 1;
		} catch { /* a parameter that will not take it is reported by the run */ }
	}
	return n;
}

/**
 * The model at a set of optimised values.
 *
 * The two buttons are genuinely different things, which is why there are two.
 *
 * **Run at these values** changes nothing: the run is made against a *copy* of
 * the model with the values put in, so what is drawn is the answer and the
 * model on screen is still the model on screen. The corner of the Chart says
 * so, because a preview that looked like an ordinary run would be the worst of
 * both.
 *
 * **Update the parameters** is the edit, written as one step so one undo takes
 * the whole answer back rather than a parameter at a time.
 */
function runAtValues(values, { keep }) {
	const named = (values ?? []).filter((v) => Number.isFinite(v.value));
	if (!named.length) return;
	if (!keep) {
		state.preview = named.map((v) => ({ key: v.key, value: v.value }));
		runSimulation({ manual: true, substitute: state.preview });
		flash('Run at the optimised values. The model itself is untouched — press Run '
			+ 'to go back to it.', 'info');
		return;
	}
	state.preview = null;
	const n = putValues(state.raw, named);
	modelChanged({ hint: 'optimised values' });
	runSimulation({ manual: true });
	flash(`${n} parameter${n === 1 ? '' : 's'} updated. One undo takes it back.`, 'info');
}

/** The times a run would report, for a model that has not run yet. */
function timesOfModel() {
	try { return Array.from(new Project(structuredClone(state.raw)).timeGrid()); } catch { return []; }
}

/**
 * Everything this tool can write, in one dialog.
 *
 * What is pickable is worked out here, where the state is, and handed over as
 * plain lists -- the dialog knows nothing about runs or models, only about
 * named things with a kind and a count.
 */
function openSave() {
	const r = state.results;
	const prob = currentProb();
	const outs = r?.outputs ?? [];
	// A block, not a series: choose `Dose` and every nuclide of it goes.
	const on = new Set(state.selected.map((i) => outs[i]?.block ?? outs[i]?.label));
	const series = blocksOf(outs).map((b) => ({
		key: b.name, name: b.name, kind: b.kind, unit: b.unit, count: b.count,
		system: b.name.includes('.') ? b.name.slice(0, b.name.lastIndexOf('.')) : '',
		on: on.has(b.name),
	}));
	// The same shape for the data side: one row per parameter or lookup table,
	// counted in the values it brings.
	const byBlock = new Map();
	for (const row of dt.collect(state.raw)) {
		const name = row.block ? (row.block.system ? `${row.block.system}.${row.block.name}` : row.block.name) : row.id;
		const found = byBlock.get(name);
		if (found) { found.count += 1; continue; }
		byBlock.set(name, {
			key: name, name, kind: row.kind, unit: row.unit, count: 1,
			system: row.block?.system ?? '',
		});
	}
	const data = [...byBlock.values()];
	const log = r && !r.detached ? runLogFor() : '';
	openSaveDialog({
		can: {
			results: !!r && !r.detached,
			sample: !!prob,
			iterations: prob?.iterations ?? 0,
			stale: !!r && state.dirty,
			data: data.length > 0,
			fileName: state.fileHandle?.name ?? null,
		},
		series,
		data,
		endpoints: ed.endpoints(state.raw),
		// What Run log would write, shown as the log window shows it -- and
		// what it then does write, rather than a log made again a moment later
		// with a later time on it.
		log,
		chosen: state.saveChoice,
		// The Ecolego export: what it would hold and leave out, shown before
		// anything is written, and then the file itself.
		eco: {
			preview: async () => {
				// A frame first, so the dialog says it is working before the
				// page is busy working it out.
				await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
				const { exportEco } = await import('../io/ecoexport.js');
				return exportEco(state.raw);
			},
			reveal: revealByName,
		},
		onSave: (choice) => {
			state.saveChoice = { kind: choice.kind, format: choice.format, holds: choice.holds, which: choice.which };
			runSave({ ...choice, log });
		},
	});
}

/**
 * What the dialog asked for, done.
 *
 * `open` sends the file to the HDF5 Browser instead of the disk. The tab is
 * opened before anything here awaits: this runs inside the click, and a
 * pop-up is allowed out of a user gesture and not out of a promise that
 * settles after one.
 */
async function runSave({ kind, format, keys, open = false, holds = 'all', which = 1, log = null, prepared = null }) {
	const handoff = open ? openResultBrowser() : null;
	if (open && !handoff) return;
	const r = state.results;
	const outs = r?.outputs ?? [];
	// Back from blocks to the series they stand for, which is what every
	// export below is indexed by.
	const idx = keys ? indicesFor(outs, keys) : null;
	const everything = idx && idx.length === outs.length;
	const suffix = everything ? '-all' : '';
	if (kind === 'model') { await saveFile(format, { prepared }); return; }
	if (kind === 'archive') {
		// Choosing here *is* choosing the endpoints: the list is a property of
		// the model, so it is written back before the file is, and a re-run
		// keeps those. Only when it has actually changed -- an edit nobody
		// made should not put a dot on Save.
		const was = ed.endpoints(state.raw).join('\u0000');
		if (keys && keys.join('\u0000') !== was) {
			ed.setEndpoints(state.raw, keys);
			modelChanged({ layoutOnly: true, hint: 'endpoints' });
		}
		await saveFile('data');
		return;
	}
	if (kind === 'results') {
		// The browser reads HDF5, whichever format the dialog was left on.
		if (format === 'csv' && !handoff) await downloadCSV(idx, suffix);
		else await downloadHDF5(idx, suffix, handoff);
		return;
	}
	if (kind === 'realisations') {
		// The file is named after what it holds: `-realisations`, `-mean`,
		// `-realisation-7`.
		await downloadRealisations(idx, null, holds === 'one' ? which : holds, handoff);
		return;
	}
	if (kind === 'data') { await exportData(handoff ? 'h5' : format, keys, handoff); return; }
	if (kind === 'log') {
		// Asks where, as every other Save does; it used to download without a
		// word and say only that the log had been written out.
		await saveText(`${slug(state.raw.name)}-run-log.txt`, log || runLogFor(), 'Run log');
	}
}

/**
 * What a file holds, and what can be done with each of those.
 *
 * Read first, asked second. Which is the only order that works: the extension
 * does not say whether a `.h5` is a thousand realisations of a release rate or
 * a table of parameter values, and a `.zip` from this tool is a model *and* a
 * run.
 */
async function chooseImport(file) {
	const name = file.name;
	const lower = name.toLowerCase();
	const holds = [];
	try {
		if (/\.xlsx$/i.test(lower) || /\.h5$|\.hdf5$|\.he5$/i.test(lower)) {
			const bytes = new Uint8Array(await file.arrayBuffer());
			const { rows, problems } = /\.xlsx$/i.test(lower)
				? await readDataWorkbook(bytes)
				: await readDataHDF5(bytes);
			const ids = new Set(rows.map((r) => r.id));
			const tables = new Set(rows.filter((r) => r.time != null).map((r) => r.id));
			const samples = rows.filter((r) => r.pdf?.kind === 'pg').length;
			holds.push({
				key: 'data',
				label: 'Data — parameters and lookup tables',
				detail: rows.length
					? `${rows.length.toLocaleString()} rows, ${ids.size.toLocaleString()} ids`
						+ (tables.size ? `, ${tables.size.toLocaleString()} lookup tables` : '')
						+ (samples ? `, ${samples.toLocaleString()} raw samples` : '')
					: '',
				why: rows.length ? null : 'Nothing in it reads as data.',
				actions: [{
					label: 'Choose what to import…', primary: true,
					title: 'Says what it would do before it does it.',
					run: () => openDataImport({
						name, rows, problems, project: state.raw,
						onApply: ({ create, keys }) => {
							const want = keys ? new Set(keys) : null;
							const take = want ? rows.filter((r) => want.has(r.id)) : rows;
							const rep = dt.apply(state.raw, take, { create });
							modelChanged({ hint: `import ${name}` });
							flash(dt.describe(rep),
								rep.unmatched.length || rep.problems.length ? 'warn' : 'info');
						},
					}),
				}],
			});
		} else {
			// A model file, in whichever of its forms -- and an archive may
			// carry a run beside it.
			let read;
			try {
				await showOpening('read', file.name);
				read = await readModelFile(file, { onStage: (stage) => showOpening(stage, file.name) });
			} finally {
				endOpening();
			}
			const { project, report, dataset, datasetProblem } = read;
			const source = ed.migrateKeys(structuredClone(project));
			ed.materialiseShorthand(source);
			const blocks = ed.blockCount ? ed.blockCount(source) : countBlocks(source);
			holds.push({
				key: 'model',
				label: 'Model',
				detail: `${blocks.toLocaleString()} blocks`,
				actions: [
					{
						label: 'Import blocks…', primary: true,
						title: 'Bring some of them into the model that is open, with a survey '
							+ 'of what each one drags along.',
						run: () => importFromFile(file),
					},
					{
						label: 'Open it',
						title: 'Replaces the model that is open.',
						// What was read just now, rather than reading it again.
						run: () => openModelFile(file, { read }),
					},
				],
			});
			holds.push({
				key: 'results',
				label: 'A saved run',
				detail: dataset ? describeDataset(dataset.meta) : '',
				why: dataset ? null
					: (datasetProblem
						? `The run in it could not be read — ${datasetProblem}`
						: 'This file has no run in it.'),
				actions: [{
					label: 'Open the model and its run', primary: true,
					title: 'The run comes back without the solve.',
					run: () => openModelFile(file, { read }),
				}],
			});
			void report;
		}
	} catch (e) {
		showError({ name: e.name ?? 'Error', message: e.message, blockName: null });
		flash(`${name} could not be read: ${e.message}`, 'warn');
		return;
	}
	openImportChooser({ name, holds, onPickAnother: () => pickFile(chooseImport) });
}

/** How many blocks a model has, for the line that says what a file holds. */
function countBlocks(project) {
	let n = 0;
	for (const key of Object.keys(project ?? {})) {
		if (Array.isArray(project[key]) && project[key][0]?.name) n += project[key].length;
	}
	return n;
}

/** A data file in: the picker, then the dialog that says what it would do. */
function importData() {
	const input = el('input', {
		type: 'file',
		accept: '.xlsx,.h5,.hdf5,.he5',
		style: 'display:none',
	});
	input.addEventListener('change', async () => {
		const file = input.files?.[0];
		input.remove();
		if (!file) return;
		try {
			const bytes = new Uint8Array(await file.arrayBuffer());
			const xlsx = /\.xlsx$/i.test(file.name);
			const { rows, problems } = xlsx
				? await readDataWorkbook(bytes)
				: await readDataHDF5(bytes);
			if (!rows.length) {
				flash(`${file.name} holds no rows this reads.`, 'warn');
				return;
			}
			openDataImport({
				name: file.name, rows, problems, project: state.raw,
				onApply: ({ create }) => {
					const rep = dt.apply(state.raw, rows, { create });
					// One edit, so one undo takes the whole import back -- which
					// is the only safe way to try one on a model somebody has
					// been working on.
					modelChanged({ hint: `import ${file.name}` });
					flash(dt.describe(rep), rep.unmatched.length || rep.problems.length ? 'warn' : 'info');
				},
			});
		} catch (e) {
			showError({ name: e.name ?? 'Error', message: e.message, blockName: null });
			flash(`${file.name} could not be read: ${e.message}`, 'warn');
		}
	});
	document.body.append(input);
	input.click();
}

/** Times in a badge: 1e6 rather than 1000000, and no trailing noise. */
const slug = (s) => (String(s ?? '').replace(/\W+/g, '-').toLowerCase()
	.replace(/^-+|-+$/g, '') || 'model');

/**
 * The results as CSV.
 *
 * @param idx    which outputs, by index; the tabulated selection by default
 * @param suffix appended to the file name, so a full export and a table
 *               export do not overwrite each other in a downloads folder
 */
async function downloadCSV(idx = null, suffix = '') {
	const r = state.results;
	if (!r) { flash('Run the model first.', 'warn'); return; }
	const cols = idx ?? (state.selected.length
		? state.selected
		: r.outputs.map((_, i) => i));
	if (!cols.length) { flash('Nothing to export.', 'warn'); return; }
	// Every scenario run beside the selected one goes too, a column per
	// output per scenario -- whether or not the legend is showing it: a file
	// is not a view.
	const beside = shownScenarioRuns({ hidden: false });
	if (!confirmHugeExport(cols.length * (beside.length + 1), r.t.length)) return;
	// The series live in the worker until asked for; an export of every
	// output asks for all of them at once, which is one pass over the rows
	// there and one message back.
	if (cols.some((i) => !r.columns[i] && r.outputs[i].constant == null && !r.local)) {
		flash(`Working out ${cols.length} column${cols.length === 1 ? '' : 's'}…`, 'info');
	}
	const spec = beside.length ? scenarioColumns(cols, { hidden: false }) : null;
	await Promise.all([ensureColumns(r, cols), ...beside.map((e) => ensureColumns(e.r,
		spec.filter((c) => c.r === e.r).map((c) => c.i)))]);
	if (state.results !== r) return;
	const heads = spec ? spec.map((c) => csvCell(c.label)) : cols.map((i) => csvCell(r.outputs[i].label));
	const vals = spec ? spec.map((c) => c.values()) : cols.map((j) => column(r, j));
	const lines = [['time', ...heads].join(',')];
	for (let i = 0; i < r.t.length; i++) {
		lines.push([r.t[i], ...vals.map((v) => v[i])].join(','));
	}
	download(`${slug(state.raw.name)}${suffix}.csv`, lines.join('\n'), 'text/csv');
	flash(`Exported ${vals.length} column${vals.length === 1 ? '' : 's'}`
		+ (spec ? ` (${beside.length + 1} scenarios)` : '')
		+ ` and ${r.t.length} row${r.t.length === 1 ? '' : 's'}.${exportCaveat()}`, 'info');
}

/**
 * Where a finished file goes: to disk, or to the tab already waiting for it.
 *
 * The two differ only here. Everything above this -- which series, which
 * realisations, building the tree -- is the same work either way, which is the
 * reason this is one function rather than a second export path.
 */
async function deliver(bytes, name, handoff) {
	const size = bytes.length >= 1048576
		? `${(bytes.length / 1048576).toFixed(1)} MB`
		: `${Math.max(1, Math.round(bytes.length / 1024))} kB`;
	if (!handoff) {
		download(name, bytes, 'application/x-hdf5');
		return { size, where: '' };
	}
	await handoff.send(name, bytes);
	return { size, where: ' — open in the HDF5 Browser' };
}

/**
 * Opens the result browser now, so an export can send to it later.
 *
 * Called from the click itself and never from anything it awaits: a pop-up is
 * allowed out of a user gesture and not out of a promise that settles after
 * one. Returns null when the browser blocked it, having said so.
 */
function openResultBrowser() {
	const handoff = openHandoff();
	if (!handoff) {
		flash('The HDF5 Browser could not be opened — allow pop-ups for this page '
			+ 'and try again.', 'warn');
	}
	return handoff;
}

/**
 * The results as HDF5, in the shape Ecolego writes and its tools read.
 *
 * CSV is a table and a result is a tree: a column called `Soil [Cs-137,
 * North]` is a name that has to be taken apart again by whoever reads it, and
 * nothing in the file says what the units are, which index list those nuclides
 * came from, or what the time column is measured in. HDF5 holds all of that,
 * and the result browser at kvotab.se opens one and draws every nuclide of a
 * block as one chart -- which is how these results are read.
 *
 * The writer is ./io/hdf5.js and the shape is ./io/resultfile.js; both are
 * loaded on demand, because a page that has not exported anything has no use
 * for either.
 *
 * @param idx    which outputs, by index; the tabulated selection by default
 * @param suffix appended to the file name, as for CSV
 */
async function downloadHDF5(idx = null, suffix = '', handoff = null) {
	const r = state.results;
	if (!r) { flash('Run the model first.', 'warn'); return; }
	const cols = idx ?? (state.selected.length
		? state.selected
		: r.outputs.map((_, i) => i));
	if (!cols.length) { flash('Nothing to export.', 'warn'); return; }
	const beside = shownScenarioRuns({ hidden: false });
	if (!confirmHugeExport(cols.length * (beside.length + 1), r.t.length)) return;
	if (cols.some((i) => !r.columns[i] && r.outputs[i].constant == null && !r.local)) {
		flash(`Working out ${cols.length} series…`, 'info');
	}
	const spec = beside.length ? scenarioColumns(cols, { hidden: false }) : null;
	await Promise.all([ensureColumns(r, cols), ...beside.map((e) => ensureColumns(e.r,
		spec.filter((c) => c.r === e.r).map((c) => c.i)))]);
	if (state.results !== r) return;
	// Scenarios beside the selected one: each series once per scenario, with
	// the scenario list as one more index of it, so the file holds a group per
	// scenario under each block the way it holds one per nuclide -- which is
	// the shape a result with a scenario dimension has in Ecolego's files.
	let outputs = r.outputs;
	let which = cols;
	let columnOf = (i) => column(r, i);
	if (spec) {
		const list = ed.scenarioList(state.raw)?.name ?? 'Scenarios';
		outputs = spec.map((c) => ({
			...c.output,
			dims: [...(c.output.dims ?? []), list],
			index: [...(c.output.index ?? []), c.scenario],
			label: c.label,
		}));
		const vals = spec.map((c) => c.values());
		which = spec.map((_, k) => k);
		columnOf = (k) => vals[k];
	}
	try {
		const [{ writeHDF5 }, { resultTree }] = await Promise.all([
			import('../io/hdf5.js'), import('../io/resultfile.js'),
		]);
		const bytes = writeHDF5(resultTree({
			t: r.t,
			outputs,
			column: columnOf,
			which,
			project: state.raw,
			indexLists: ed.indexLists(state.raw),
		}));
		const { size, where } = await deliver(
			bytes, handoffName(slug(state.raw.name), suffix), handoff);
		flash(`Exported ${which.length} series`
			+ (spec ? ` (${beside.length + 1} scenarios)` : '')
			+ ` and ${r.t.length} times, ${size}${where}.${exportCaveat()}`, 'info');
	} catch (e) {
		handoff?.cancel();
		flash(`Could not write the HDF5 file: ${e.message}`, 'warn');
	}
}

/**
 * Every realisation, as HDF5.
 *
 * The other export writes the curve; this writes the sample it came from --
 * one row per output time, one column per realisation, which is the shape
 * the desktop tools' probabilistic files are in, and the one the result browser
 * reads. It draws the mean from it and can put a confidence band round it,
 * neither of which is stored: what is stored is the runs, and everything else
 * is derived from them by whoever is asking.
 *
 * The matrix never reached the page from the probabilistic run -- a thousand
 * realisations of a hundred series is 280 MB and the chart wanted five curves
 * of it -- so it is fetched now, for the series being written and no others.
 *
 * @param idx    which outputs, by index into the deterministic list
 * @param suffix appended to the file name
 * @param want   `'all'` for the matrix, `'mean'` for the average of the runs,
 *               or a realisation number (from 1) for a single one of them
 */
async function downloadRealisations(idx = null, suffix = null, want = 'all', handoff = null) {
	const r = state.results;
	const prob = currentProb();
	if (!r) { flash('Run the model first.', 'warn'); return; }
	if (!prob) {
		flash('Run the model probabilistically first.', 'warn');
		return;
	}
	const cols = idx ?? (state.selected.length
		? state.selected
		: r.outputs.map((_, i) => i));

	// Matched by label, because a probabilistic run keeps the series it was
	// asked for and the table's selection is over all of them.
	const at = new Map(prob.outputs.map((o, k) => [o.label, k]));
	const pairs = cols
		.map((i) => ({ i, k: at.get(r.outputs[i]?.label) }))
		.filter((p) => p.k !== undefined);
	if (!pairs.length) {
		flash('None of these series were part of the probabilistic run.', 'warn');
		return;
	}
	const left = cols.length - pairs.length;

	// What was asked for, in the three forms it can take: every run, their
	// mean, or one of them by number. The number is 1-based on the screen and
	// 0-based on the wire, which is the only place the two meet.
	const all = want === 'all';
	const mean = want === 'mean';
	const one = all || mean
		? -1
		: Math.min(prob.iterations, Math.max(1, Math.round(Number(want)) || 1)) - 1;
	const named = all ? 'realisations' : mean ? 'mean' : `realisation ${one + 1}`;
	const fileSuffix = suffix ?? (all ? '-realisations' : mean ? '-mean' : `-realisation-${one + 1}`);

	// Four bytes a value, and for the matrix there are `iterations` times as
	// many values as a deterministic export has. Asked about before anything is
	// allocated -- and only for the matrix, since a mean or a single run is the
	// size of an ordinary export.
	// The sample's own times. Every realisation is reported on the model's
	// grid, which is not the run's own when that reports the solver's steps
	// (the far field does): the file used to take the run's times, and the
	// matrices did not fit them.
	const times = prob.t;
	const bytes = all
		? pairs.reduce((sum, p) => sum
			+ (r.outputs[p.i]?.timeDependent === false ? 1 : times.length) * prob.iterations * 4, 0)
		: 0;
	if (bytes > HUGE_EXPORT) {
		const go = window.confirm(
			`${pairs.length.toLocaleString()} series × ${prob.iterations.toLocaleString()} `
			+ `realisations × ${times.length.toLocaleString()} times is about `
			+ `${(bytes / 1073741824).toFixed(1)} GB. It has to be built in memory before it `
			+ 'can be saved. Export it anyway?\n\nFewer series, or a run with fewer '
			+ 'realisations, is the way to a file that will open.');
		if (!go) { flash('Did not export.', 'info'); return; }
	}

	flash(all
		? `Collecting ${pairs.length.toLocaleString()} × `
			+ `${prob.iterations.toLocaleString()} realisations…`
		: `Working out the ${named}…`, 'info');
	let reply;
	try {
		reply = await askProbMatrices(pairs.map((p) => p.k), all ? 'all' : mean ? 'mean' : one, { compact: true });
	} catch (e) {
		flash(`Could not read the realisations: ${e.message}`, 'warn');
		return;
	}
	if (!reply) {
		handoff?.cancel();
		flash('The realisations are no longer held — run the model probabilistically again.',
			'warn');
		return;
	}
	if (currentProb() !== prob || state.results !== r) { handoff?.cancel(); return; }

	const got = new Map();
	reply.indices.forEach((k, n) => got.set(k, reply.matrices[n]));
	const forOutput = (i) => got.get(at.get(r.outputs[i]?.label)) ?? null;
	try {
		const [{ writeHDF5 }, { resultTree }] = await Promise.all([
			import('../io/hdf5.js'), import('../io/resultfile.js'),
		]);
		const bytesOut = writeHDF5(resultTree({
			t: times,
			outputs: r.outputs,
			// A mean or a single run is one curve like any other, so it arrives
			// the way every other curve does. Only the matrix needs the shape.
			// Every series written is one the sample kept (`pairs`), so each has
			// its curve on the sample's times; the run's own column is on the
			// run's times and is never the one to fall back on.
			column: (i) => forOutput(i) ?? new Float64Array(times.length).fill(NaN),
			which: pairs.map((p) => p.i),
			project: state.raw,
			indexLists: ed.indexLists(state.raw),
			...(all
				? { realisations: { iterations: reply.iterations, matrixFor: forOutput } }
				: { sample: { iterations: reply.iterations, of: mean ? 'mean' : one + 1 } }),
		}));
		const { size, where } = await deliver(
			bytesOut, handoffName(slug(state.raw.name), fileSuffix), handoff);
		flash(`Exported ${pairs.length} series over ${times.length} times — `
			+ (all
				? `${reply.iterations.toLocaleString()} realisations each`
				: mean
					? `the mean of ${reply.iterations.toLocaleString()} realisations`
					: `realisation ${one + 1} of ${reply.iterations.toLocaleString()}`)
			+ `, ${size}${where}.`
			+ (left ? ` ${left} not in the run were left out.` : ''), 'info');
	} catch (e) {
		handoff?.cancel();
		flash(`Could not write the HDF5 file: ${e.message}`, 'warn');
	}
}

/**
 * What can be done to the chart.
 *
 * The scales live here rather than above the chart because they are read far
 * less often than they are looked at: log-log is what an activity-versus-time
 * result is read in, and the toggles were two permanent controls for a choice
 * almost nobody changes. Saving a picture has nowhere else to be: the chart is
 * a canvas, and a canvas has no menu of its own.
 */
function chartMenu(ev) {
	ev.preventDefault();
	const has = !!state.results && state.selected.length > 0;
	const scale = (key, label, hint) => ({
		label,
		hint,
		checked: () => !!state[key],
		keepOpen: true,
		title: `Logarithmic ${label.replace('log ', '')} axis. Off draws it `
			+ `linearly, which suits a result that spans one decade rather `
			+ `than five.`,
		onPick: () => {
			state[key] = !state[key];
			if (state.results) renderChart();
		},
	});
	openMenu({
		x: ev.clientX,
		y: ev.clientY,
		title: 'chart',
		items: [
			scale('xLog', 'log time', 'x'),
			scale('yLog', 'log value', 'y'),
			{ separator: true },
			{
				label: 'Save as picture',
				disabled: !has,
				title: has
					? 'The chart as it is on screen, with a legend when it has more '
						+ 'lines than it labels directly — and without the crosshair.'
					: 'There is nothing on the chart yet',
				items: Object.entries(PICTURE_KINDS).map(([kind, spec]) => ({
					label: spec.label,
					title: kind === 'svg'
						? 'Lines and text rather than pixels: it scales to any size, '
							+ 'and the lettering can be changed in a drawing program.'
						: kind === 'jpeg'
							? 'Photographic compression, so thin lines soften a little; '
								+ 'PNG is the better choice for a chart.'
							: 'Pixels, at twice the size on screen so it stays sharp '
								+ 'in print.',
					onPick: () => saveChartPicture(kind),
				})),
			},
			{ separator: true },
			{
				label: 'Zoom in',
				hint: 'scroll',
				disabled: !has,
				onPick: () => chart?.zoomBy(1.6),
			},
			{
				label: 'Zoom out',
				hint: 'scroll',
				disabled: !has,
				onPick: () => chart?.zoomBy(1 / 1.6),
			},
			{
				label: 'Drag to pan',
				checked: () => !!chart?.dragPans,
				keepOpen: true,
				title: 'What a plain drag does: move the chart under the pointer, '
					+ 'or draw a rectangle to zoom into. Holding shift does the '
					+ 'other one either way, and the middle button always pans.',
				onPick: () => chart?.setDragPans(!chart.dragPans),
			},
			{
				label: 'Show everything',
				hint: 'double-click',
				disabled: !chart?.isZoomed(),
				title: chart?.isZoomed()
					? 'Back to the whole of the results, at the scale they need'
					: 'The chart is already showing everything',
				onPick: () => chart?.resetZoom(),
			},
			{ separator: true },
			{
				label: 'Export the numbers to CSV',
				hint: `${state.selected.length} column${state.selected.length === 1 ? '' : 's'}`,
				disabled: !has,
				onPick: () => downloadCSV(state.selected.slice(), ''),
			},
		],
	});
}

async function saveChartPicture(kind) {
	if (!chart) return;
	try {
		const { file, width, height } = await chart.savePicture(kind, {
			name: ed.modelName(state.raw),
		});
		flash(`Saved ${file} — ${Math.round(width)}×${Math.round(height)}`
			+ (kind === 'svg' ? '.' : ' at 2× for print.'), 'info');
	} catch (e) {
		flash(`The picture could not be saved: ${e.message}`, 'warn');
	}
}

async function openSavedTimes() {
	// Caught here: the callers are event handlers whose own try/catch cannot
	// see a rejected promise, so a failed fetch of the module was an
	// unhandled rejection in the console and nothing on screen.
	try {
		const { openOutputTimes } = await import('./outputtimes.js');
		openOutputTimes(state.raw, { onChange: modelChanged, onStatus: flash });
	} catch (e) {
		flash(`Could not open the saved-times editor: ${e.message}`, 'warn');
	}
}

/**
 * Right-clicking the table.
 *
 * The export used to be a button in the tab bar, which is an odd place for it:
 * it acts on the table, so it belongs to the table. What it holds, as CSV, as
 * HDF5, or into the HDF5 Browser; every other file is in Save….
 */
function tableMenu(ev) {
	ev.preventDefault();
	const r = state.results;
	if (!r) return;
	const shown = state.selected.length;
	// What the table holds, three ways, and nothing else: every other file --
	// every output, the realisations, the endpoints -- is in Save…, which says
	// what each one is.
	openMenu({
		x: ev.clientX,
		y: ev.clientY,
		title: 'table',
		items: [
			{
				label: 'Export table to CSV',
				hint: `${shown} column${shown === 1 ? '' : 's'}`,
				disabled: !shown,
				onPick: () => downloadCSV(state.selected.slice(), ''),
			},
			{
				label: 'Export table to HDF5',
				hint: `${shown} series`,
				disabled: !shown,
				title: 'A .h5 file: the times in /time, '
					+ 'the index lists in /IndexLists, and one dataset per series '
					+ 'under its block. The HDF5 Browser at kvotab.se reads it.',
				onPick: () => downloadHDF5(state.selected.slice(), ''),
			},
			{
				label: 'Open in the HDF5 Browser',
				hint: `${shown} series`,
				disabled: !shown,
				title: 'Opens the HDF5 Browser at kvotab.se and hands it these series '
					+ 'directly, without saving a file first.',
				onPick: () => {
					const handoff = openResultBrowser();
					if (handoff) downloadHDF5(state.selected.slice(), '', handoff);
				},
			},
		],
	});
}

/**
 * Writes the model out, asking where it should go.
 *
 * The ellipsis on the button is a promise: **Save…** opens a chooser rather
 * than dropping a file into whatever folder the browser downloads into. A
 * model is somebody's work and belongs beside the rest of their project, and a
 * downloads folder with four `landscape.json` files in it, numbered, is not a
 * place anything can be found again.
 *
 * `showSaveFilePicker` is the real thing: the operating system's own save
 * dialog, a folder of the user's choosing, and a file overwritten in place
 * rather than duplicated. Firefox and Safari do not have it, and nothing in a
 * page can conjure one -- there the browser's own "ask where to save each
 * file" setting is the only lever, so the link-and-click download stands in
 * and the notice says where the file went, which is the one thing the user
 * cannot see for themselves.
 */
/**
 * The model as bytes, in whichever form the name asks for.
 *
 * A model is repetitive text and compresses well -- `biosphere.json` to a fifth
 * of itself, a large assessment from 36 MB to 16 -- and the file is often on its
 * way somewhere: into a repository, attached to a mail, onto a memory stick. So
 * the format follows the extension the file ends up with, which is a thing the
 * person saving already has to choose and does not have to be asked about
 * twice.
 *
 * `.zip` is the default of the two compressed forms because it is what
 * double-clicks open on every desktop. `.json.gz` is there because it is what a
 * command line makes, and a project kept under version control is more likely
 * to be that.
 *
 * Falls back to plain text rather than failing: a browser too old to compress
 * still saves the model, which is what matters.
 *
 * @returns {Promise<{name: string, body: string|Uint8Array, type: string}>}
 */
export async function modelFileFor(name, model = state.raw, { extra = null, prepared = null } = {}) {
	const text = JSON.stringify(model, null, 2);
	const lower = name.toLowerCase();
	const inner = `${slug(model?.name)}.json`;

	// An Ecolego project: the model written in another tool's terms, with a
	// report of what those terms have no place for. See ../io/ecoexport.js.
	if (lower.endsWith('.eco')) {
		if (extra?.length) {
			throw new Error(`A run cannot be saved inside an .eco project, and '${name}' is one.`);
		}
		// The export the Save dialog showed the report of, where there is one:
		// the same model, so the same file, and not worked out twice.
		const { exportEco } = await import('../io/ecoexport.js');
		const { bytes, report } = await (prepared ?? exportEco(model));
		return { name, body: bytes, type: 'application/zip', report };
	}

	if (lower.endsWith('.zip')) {
		const { zip } = await import('../io/zip.js');
		// The model first and at the root, whatever else is in the archive:
		// that is where a reader that knows nothing about results looks for it,
		// which is what keeps a results file an ordinary model file as well.
		const bytes = await zip([
			{ name: inner, bytes: new TextEncoder().encode(text) },
			...(extra ?? []),
		]);
		return { name, body: bytes, type: 'application/zip' };
	}
	// Only a ZIP can hold two things. Asked for a run inside a `.json` or a
	// `.json.gz`, this writes the model and says nothing -- which would be a
	// file quietly missing what it was saved for, so the caller is stopped
	// before it gets here rather than surprised afterwards.
	if (extra?.length) {
		throw new Error(`A run can only be saved inside a .zip, and '${name}' is not one.`);
	}
	if (lower.endsWith('.gz')) {
		const { gzip } = await import('../io/gzip.js');
		const bytes = await gzip(new TextEncoder().encode(text));
		if (bytes) return { name, body: bytes, type: 'application/gzip' };
		// No compression to be had here. Saved as what it is rather than under
		// a name that promises something the bytes are not.
		return { name: name.replace(/\.gz$/i, ''), body: text, type: 'application/json' };
	}
	return { name, body: text, type: 'application/json' };
}

/**
 * How much smaller it came out, for the notice.
 *
 * A file with a run in it is not smaller than the model and saying so would be
 * nonsense, so that one is measured against itself: what it holds, and how big
 * it is.
 */
function savedSize(body, text, extra = null) {
	if (typeof body === 'string') return '';
	const kB = Math.round(body.length / 1024).toLocaleString();
	if (extra?.length) {
		const raw = extra.reduce((n, e) => n + e.bytes.length, 0);
		return ` — ${kB} kB, model and results, from `
			+ `${Math.round(raw / 1024).toLocaleString()} kB of numbers`;
	}
	const from = new TextEncoder().encode(text).length;
	return ` — ${kB} kB, `
		+ `${(100 - (100 * body.length) / from).toFixed(0)}% smaller than the JSON`;
}

async function saveFile(as = 'json', { prepared = null } = {}) {
	const base = slug(state.raw.name);
	const name = as === 'zip' ? `${base}.zip`
		: as === 'gz' ? `${base}.json.gz`
			: as === 'data' ? `${base}-results.zip`
				: as === 'eco' ? `${base}.eco`
					: `${base}.json`;
	const text = JSON.stringify(state.raw, null, 2);

	// The run itself, fetched before the dialog opens: it is a round trip to
	// the worker and it can be refused -- no run, a stopped worker -- and
	// finding that out *after* somebody has chosen a folder would be a save
	// that asked and then failed.
	let extra = null;
	if (as === 'data') {
		// The model in the archive has to be the model the run was made from,
		// or the file is a pair of things that do not go together -- a chart of
		// one model's numbers under another's labels, which is the failure
		// ../io/dataset.js exists to prevent and which the layout signature
		// cannot catch when only a rate has changed. This is the same test the
		// dot on Run already shows, so the refusal is in words somebody has
		// already seen.
		if (state.dirty) {
			showError({
				name: 'Save with results',
				message: 'The model has changed since this run, so the results in the '
					+ 'file would not be the results of the model in it.',
				hint: 'Press Run and save again, or use Save… for the model on its own.',
			});
			return;
		}
		try {
			extra = await requestDataset(`${base}.json`);
		} catch (e) {
			showError({
				name: 'Save with results', message: e.message,
				hint: 'Save… still writes the model on its own.',
			});
			return;
		}
	}
	if (typeof window.showSaveFilePicker === 'function') {
		let handle = null;
		try {
			handle = await window.showSaveFilePicker({
				suggestedName: name,
				// All three, with the one that was asked for first: the dialog
				// picks the format from the type that is selected, so the
				// order is the default and the rest are one menu away without
				// coming back here.
				types: saveTypes(as),
			});
		} catch (e) {
			// Cancelling is an answer, not a failure: nothing is saved and
			// nothing is said. Anything else -- the API refused, the page is
			// somewhere it may not ask -- falls through to the download, since
			// the point of pressing Save is to end up with a file.
			if (e?.name === 'AbortError') return;
			handle = null;
		}
		if (handle) {
			try {
				// By the name it ended up with, not the one that was offered:
				// the dialog lets the format be changed, and typing `.zip`
				// should produce a ZIP whichever entry was highlighted.
				const written = modelToWrite(handle.name);
				const file = await modelFileFor(handle.name, written, { extra, prepared });
				const to = await handle.createWritable();
				await to.write(file.body);
				await to.close();
				adoptStamps(written);
				// An export is somebody else's file about this model, and what
				// it could not hold is the first thing worth reading about it.
				if (file.report) {
					exportedFile(file, handle.name);
					return;
				}
				// The file this model is now in. Saving with the results is a
				// different file about the same model -- an archive, not the
				// model -- so it is not the one Save writes to next time.
				if (as !== 'data') noteSaved(handle);
				flash(`Saved ${handle.name}${savedSize(file.body, text, extra)}.`, 'info');
			} catch (e) {
				showError({
					name: 'Save', message: `Could not write the file: ${e.message}`,
					hint: 'The folder may be read-only, or permission may have been '
						+ 'withdrawn. Try Save… again and pick another place.',
				});
			}
			return;
		}
	}
	const written = modelToWrite(name);
	const file = await modelFileFor(name, written, { extra, prepared });
	download(file.name, file.body, file.type);
	adoptStamps(written);
	if (file.report) {
		exportedFile(file, file.name);
		return;
	}
	// Downloaded rather than written: there is no file to write to again, but
	// the model *has* been written out, and saying otherwise would leave the
	// button claiming unsaved work on a browser that simply has no picker.
	if (as !== 'data') noteSaved(null);
	flash(`Saved ${file.name}${savedSize(file.body, text, extra)} to wherever this `
		+ 'browser puts downloads — it has no "save as" dialog for a page to open.',
	'info');
}

/**
 * What Save does once the model has a file: writes to it, and says so quietly.
 *
 * The ellipsis on the button is a promise that it will ask. Once it has been
 * asked and answered there is nothing left to ask, and asking again -- every
 * time, for the rest of the session -- is the thing that made saving feel like
 * exporting. So the label loses its ellipsis with the first answer, and this
 * writes straight through.
 *
 * A handle can stop working between one save and the next: the folder goes
 * away, permission is withdrawn, the file is deleted underneath. That is not
 * an error to report, it is a reason to ask again -- so it falls back to the
 * chooser, which is what the reader would have done next anyway.
 */
async function saveToFile() {
	const handle = state.fileHandle;
	if (!handle) { await saveFile('json'); return; }
	try {
		const written = modelToWrite(handle.name);
		const file = await modelFileFor(handle.name, written, {});
		const to = await handle.createWritable();
		await to.write(file.body);
		await to.close();
		adoptStamps(written);
		noteSaved(handle);
		flash(`Saved ${handle.name}.`, 'info');
	} catch (e) {
		if (e?.name === 'AbortError') return;
		state.fileHandle = null;
		flash(`${handle.name} could not be written to (${e.name ?? 'error'}) — `
			+ 'choose where to put it.', 'warn');
		await saveFile('json');
	}
}

/**
 * The model as a file of it is written: a copy stamped with the time it was
 * saved (see `stampSaved`), or, for an export, the model as it is -- an
 * Ecolego project is another tool's file about this model, not a save of it.
 */
function modelToWrite(name) {
	return /\.eco$/i.test(name) ? state.raw : ed.stampSaved({ ...state.raw }, new Date());
}

/**
 * The stamps a file was written with, now the model's own -- once it has
 * actually been written, so a save that failed half-way does not claim one.
 */
function adoptStamps(written) {
	if (written === state.raw) return;
	ed.keepStamps(state.raw, written);
	$('.model-dates')?.replaceWith(modelDatesLine(state.raw));
}

/** Records that the model as it stands is in a file, and redraws the button. */
function noteSaved(handle) {
	state.fileHandle = handle;
	state.savedRev = state.rev;
	renderSaveButton();
}

/**
 * The Save button says two things: whether it will ask, and whether there is
 * anything to write.
 *
 * Both were missing. Every press opened the chooser however many times it had
 * been answered, and nothing anywhere said whether the model in front of you
 * had been written out since the last edit -- which is the one question a Save
 * button exists to answer.
 */
function renderSaveButton() {
	const b = $('#save');
	if (!b) return;
	const named = !!state.fileHandle;
	const unsaved = state.savedRev !== state.rev;
	b.textContent = named ? 'Save' : 'Save\u2026';
	b.classList.toggle('is-unsaved', unsaved);
	b.title = named
		? (unsaved
			? `Write this model back to ${state.fileHandle.name} (\u2318S). `
				+ 'It has changed since it was last written.'
			: `Saved to ${state.fileHandle.name}. Nothing has changed since.`)
		: 'Save this model as JSON — asks where to put it (\u2318S)';
}

/** The formats the save dialog offers, the one that was asked for first. */
function saveTypes(as) {
	const all = {
		json: { description: 'Kompartment model (JSON)', accept: { 'application/json': ['.json'] } },
		zip: { description: 'Kompartment model, compressed (ZIP)', accept: { 'application/zip': ['.zip'] } },
		gz: { description: 'Kompartment model, compressed (gzip)', accept: { 'application/gzip': ['.json.gz'] } },
	};
	// A run only fits in a ZIP, so that is the only thing offered for one: a
	// dialog that let somebody pick `.json` there would write a model and
	// silently drop what they pressed the button for.
	if (as === 'data') {
		return [{
			description: 'Kompartment model and results (ZIP)',
			accept: { 'application/zip': ['.zip'] },
		}];
	}
	// An export is offered on its own for the same reason: picking `.json` in
	// a dialog opened to export would write a model file, not an export.
	if (as === 'eco') {
		return [{ description: 'Ecolego project (.eco)', accept: { 'application/zip': ['.eco'] } }];
	}
	const order = as === 'zip' ? ['zip', 'json', 'gz']
		: as === 'gz' ? ['gz', 'json', 'zip']
			: ['json', 'zip', 'gz'];
	return order.map((k) => all[k]);
}

// `.eas` alongside `.eco`: an assessment file is the same archive with the
// results of a run in it -- model.xml, views.xml and simulation.xml at the
// root, plus a `simulation/` folder of `.dta` result files this tool has no
// use for. The model in it reads exactly the same way.
const OPEN_ACCEPT = '.json,.zip,.gz,.eco,.eas,.xml,application/json,application/zip';

function openFile() {
	pickFile((f) => openModelFile(f));
}

/**
 * The file picker, shared by Open… and Import… so both accept the same things.
 *
 * In the document rather than loose: a detached `<input type=file>` opens the
 * chooser in every browser this runs in, but it is not a node anything else
 * can see -- which makes the one gesture in the application that reaches
 * outside it the one gesture that cannot be driven from a test. Hidden, and
 * taken out again once the file is in hand.
 */
function pickFile(then) {
	const input = el('input', {
		type: 'file', accept: OPEN_ACCEPT, id: 'file-picker', hidden: true,
	});
	input.addEventListener('change', () => {
		const f = input.files?.[0];
		input.remove();
		if (f) then(f);
	});
	document.body.append(input);
	input.click();
}

/**
 * Reads a model file without opening it.
 *
 * The half of `openModelFile` that turns bytes into a model, so that importing
 * blocks out of a file accepts exactly what opening one does -- including the
 * .eco and .eas archives, which are the files this is actually for.
 *
 * @returns {Promise<{project: object, report: object|null}>}
 */
/** Where a saved run lives inside a model archive. See ../io/dataset.js. */
const DATASET_DIR = 'results/';

export async function readModelFile(file, { onStage = null } = {}) {
	const lower = file.name.toLowerCase();
	// The name goes in because the file knows things the model does not: every
	// Ecolego project in the corpus calls itself `model`, and the file's own
	// name is the one anybody uses for it. See `describeModel`.
	if (lower.endsWith('.eco') || lower.endsWith('.eas')) {
		const { importEcoFile } = await import('../io/eco.js');
		return importEcoFile(await file.arrayBuffer(), { fileName: file.name, onStage });
	}

	// What it *is*, from its first four bytes, rather than what it is called.
	//
	// A compressed model can arrive under any of several names -- `.zip`,
	// `.json.zip`, `.json.gz`, or a `.json` that somebody compressed and did
	// not rename -- and the extension is the least reliable thing about a file
	// somebody has been keeping in a repository or mailing about. Four bytes
	// settle it, and reading four bytes of a 35 MB file costs nothing.
	const head = new Uint8Array(await file.slice(0, 4).arrayBuffer());
	const isZip = head[0] === 0x50 && head[1] === 0x4b && head[2] === 0x03 && head[3] === 0x04;
	const isGz = head[0] === 0x1f && head[1] === 0x8b;

	if (isZip) {
		const { unzip, entryText } = await import('../io/zip.js');
		const entries = await unzip(await file.arrayBuffer());
		// An Ecolego project is a ZIP too, and it is the one with a model.xml
		// in it -- so an archive is asked what it holds rather than what it is
		// called. `.eco` above is the fast path, not the only one.
		if ([...entries.keys()].some((n) => /(^|\/)model\.xml$/i.test(n))) {
			const { importEcoFile } = await import('../io/eco.js');
			return importEcoFile(await file.arrayBuffer(), { fileName: file.name, onStage });
		}
		// The model is at the root; a run, if the archive carries one, is under
		// `results/`. Both are looked for, and a `results/` entry that will not
		// read costs the model nothing -- see ../io/dataset.js.
		const jsonName = [...entries.keys()]
			.filter((n) => !n.startsWith(DATASET_DIR))
			.find((n) => /\.json$/i.test(n));
		if (!jsonName) {
			throw new Error(`'${file.name}' is a ZIP archive with no model in it — `
				+ `no .json file and no model.xml. It holds ${[...entries.keys()]
					.slice(0, 4).join(', ')}.`);
		}
		if (onStage) await onStage('json');
		const project = JSON.parse(entryText(entries.get(jsonName)));
		const { isDataset, readDataset } = await import('../io/dataset.js');
		if (!isDataset(entries)) return { project, report: null };
		try {
			return { project, report: null, dataset: readDataset(entries) };
		} catch (e) {
			// The model is the thing somebody opened. A run that will not read
			// is reported and dropped, not allowed to take the file with it.
			return { project, report: null, datasetProblem: e.message };
		}
	}

	if (isGz) {
		const { gunzip } = await import('../io/gzip.js');
		const text = new TextDecoder('utf-8')
			.decode(await gunzip(new Uint8Array(await file.arrayBuffer())));
		// Whatever was compressed: a project, or a bare model.xml somebody
		// gzipped.
		if (text.trimStart().startsWith('<')) {
			const { importModelXMLStepwise } = await import('../io/eco.js');
			return importModelXMLStepwise(text, { fileName: file.name }, onStage);
		}
		if (onStage) await onStage('json');
		return { project: JSON.parse(text), report: null };
	}

	if (lower.endsWith('.xml')) {
		const { importModelXMLStepwise } = await import('../io/eco.js');
		return importModelXMLStepwise(await file.text(), { fileName: file.name }, onStage);
	}
	if (lower.endsWith('.json') || file.type === 'application/json') {
		const text = await file.text();
		if (onStage) await onStage('json');
		return { project: JSON.parse(text), report: null };
	}
	// Named rather than guessed: reading an unknown file as JSON gives a parse
	// error that says nothing about what went wrong.
	throw new Error(`'${file.name}' is not a model file. Choose a .json project `
		+ '(compressed as .zip or .json.gz if you like), an Ecolego .eco project '
		+ 'or .eas assessment, or a bare model.xml.');
}

/**
 * Brings blocks out of another model file into this one.
 *
 * The file is read but never opened: what is on screen stays on screen, and
 * the dialog decides what crosses over. See ../domain/import.js for what has
 * to be decided and why.
 */
async function importFromFile(file) {
	try {
		const { project, report } = await readModelFile(file);
		const source = ed.migrateKeys(project);
		ed.materialiseShorthand(source);
		clearError();
		const { openImportDialog } = await import('./importblocks.js');
		openImportDialog({
			target: state.raw,
			source,
			fileName: file.name,
			onStatus: flash,
			onPickAnother: () => pickFile(importFromFile),
			onImport: (done) => {
				// One edit, through the one funnel: the model is re-rendered,
				// re-run and -- because every edit goes into the undo stack --
				// the whole import is a single Cmd+Z.
				modelChanged();
				if (done.added.length) {
					setSelection(
						{ kind: ed.findBlock(state.raw, done.added[0])?.kind, name: done.added[0] },
						done.added,
					);
				}
				showBlockImportReport(done, file.name, report);
			},
		});
	} catch (e) {
		showError({ name: e.name ?? 'Import', message: e.message });
	}
}

/**
 * What an import of blocks actually did.
 *
 * In the strip the .eco import report uses, for the same reason it exists: an
 * import that quietly dropped a dimension would look like a model that works
 * and answers differently.
 */
function showBlockImportReport(done, fileName, fileReport) {
	const box = $('#import-report');
	box.replaceChildren();
	const heading = el('div', { className: 'ir-head' },
		el('b', {}, `Imported ${done.added.length} block${done.added.length === 1 ? '' : 's'} `
			+ `from ${fileName}`));
	const close = el('button', { className: 'ghost ir-close', type: 'button' }, 'Dismiss');
	close.addEventListener('click', () => { box.hidden = true; });
	heading.append(close);
	box.append(heading);

	const said = [];
	if (done.listsAdded.length) {
		said.push(`${done.listsAdded.map((l) => `${l.name} (${l.indices})`).join(', ')} added`);
	}
	for (const a of done.indicesAdded) {
		said.push(`${a.indices.join(', ')} added to ${a.list}`);
	}
	for (const [from, to] of done.renamedLists) said.push(`${from} became ${to}`);
	if (said.length) box.append(el('p', { className: 'ir-counts' }, said.join(' · ')));

	if (done.renamed.length) {
		box.append(el('details', { className: 'ir-details' },
			el('summary', {}, `${done.renamed.length} name${done.renamed.length === 1 ? '' : 's'} `
				+ 'already used here'),
			el('p', { className: 'ir-hint' },
				done.renamed.map(([from, to]) => `${from} → ${to}`).join(', '))));
	}
	if (done.dimensionsDropped.length) {
		box.append(el('p', { className: 'ir-warn' },
			`Imported without ${done.dimensionsDropped.join(', ')}: `
			+ 'those blocks now hold one value where they held a grid.'));
	}
	if (done.lostEntries) {
		box.append(el('p', { className: 'ir-warn' },
			`${done.lostEntries} per-index value${done.lostEntries === 1 ? '' : 's'} `
			+ (done.dimensionsDropped.length
				? 'went with the dimensions they were keyed by. '
				: 'are keyed by an index this model does not have, and could not be '
					+ 'kept. ')
			+ 'The block’s own value is what those cells now read.'));
	}
	if (done.shadowed.length) {
		box.append(el('p', { className: 'ir-warn' },
			`${done.shadowed.length} reference${done.shadowed.length === 1 ? '' : 's'} `
			+ 'now mean a different block, because the name is taken where they landed: '
			+ `${done.shadowed.slice(0, 4).map((s) => `${s.block} reads ${s.reference}`).join(', ')}.`));
	}
	// A file that could not be read in full is worth saying twice: what was
	// left out of the file is left out of what was imported from it.
	for (const w of fileReport?.warnings ?? []) box.append(el('p', { className: 'ir-warn' }, w));
	if (fileReport?.skipped?.length) {
		box.append(el('p', { className: 'ir-warn' },
			`${fileReport.skipped.length} block${fileReport.skipped.length === 1 ? '' : 's'} `
			+ 'in that file have no equivalent in this tool and were not offered.'));
	}

	box.hidden = false;
	selectTab('build');
}

/**
 * Opens one model file, whichever of the three forms it is in.
 *
 * Shared by the Open… button and by dropping a file on the window, so both
 * routes accept exactly the same things and fail the same way.
 */
/**
 * Past this many bytes a file is asked about before it is read.
 *
 * The whole file is read into memory and the import runs on this thread, so
 * a multi-gigabyte `.eas` dropped by mistake -- results folders travel with
 * a model in that format -- froze the page with no way out. The largest
 * real project here is 11 MB; a question at twenty times that costs a click
 * on the day it is genuinely wanted.
 */
const LARGE_FILE = 200 * 1024 * 1024;

/**
 * Past this, an export is asked about first.
 *
 * A whole-model export is built in memory before the browser is handed it, so
 * the question is not how patient you are but whether the tab can hold it.
 * Half a gigabyte of numbers is the point where that stops being certain.
 */
const HUGE_EXPORT = 512 * 1024 * 1024;

/**
 * @param {File} file
 * @param {{read?: object}} [opts]  `read` is what `readModelFile` already made of
 *   the file -- the Import… chooser reads it to say what it holds -- so that
 *   opening it does not read it all again
 */
async function openModelFile(file, { read = null } = {}) {
	if (file.size > LARGE_FILE) {
		const mb = Math.round(file.size / 1048576);
		const go = window.confirm(
			`${file.name} is ${mb} MB. Reading it will take a while and may run this `
			+ 'tab out of memory. Open it anyway?',
		);
		if (!go) { flash(`Did not open ${file.name}.`, 'info'); return; }
	}
	try {
		if (!read) await showOpening('read', file.name);
		const { project, report, dataset, datasetProblem } = read
			?? await readModelFile(file, { onStage: (stage) => showOpening(stage, file.name) });
		await showOpening('setup', file.name);
		setModel(project, { label: file.name });
		if (report) showImportReport(report, file.name);
		if (datasetProblem) {
			flash(`${file.name} carries a saved run that could not be read: `
				+ `${datasetProblem} The model opened without it.`, 'warn');
		} else if (dataset) {
			openDataset(dataset, file.name);
		}
	} catch (e) {
		showError({ name: e.name ?? 'Open', message: e.message });
	} finally {
		endOpening();
	}
}

/**
 * Where opening a file has got to, in the footer's bar.
 *
 * Opening a large model takes seconds -- the largest imported assessment is a
 * 37 MB model.xml, 0.2 s of it parsing the XML, 0.15 s reading its blocks,
 * 0.75 s setting it up, and a slower machine takes two or three times that --
 * and each of those holds the page while it runs. A page that has gone quiet
 * for that long looks stuck. So the open is taken a step at a time, and
 * between steps the bar says which and how far along the whole it is, and is
 * given a frame to be painted in before the next step holds the page again.
 */
const OPENING_STAGE = {
	read: [0.03, 'Reading the file'],
	unzip: [0.08, 'Opening the archive'],
	xml: [0.15, 'Reading model.xml'],
	json: [0.3, 'Reading the model'],
	blocks: [0.45, 'Reading the blocks'],
	settings: [0.65, 'Connecting the blocks'],
	setup: [0.8, 'Setting the model up'],
};

async function showOpening(stage, fileName = '') {
	// A run's bar is the run's: an open that starts one hands it over.
	if (state.running) return;
	const [fraction, words] = OPENING_STAGE[stage] ?? [null, String(stage)];
	const bar = $('#progress');
	const text = $('#progress-pct');
	if (!bar || !text) return;
	$('#run-progress').classList.add('is-on');
	bar.removeAttribute('data-loading');
	bar.setAttribute('data-opening', stage);
	bar.max = 1;
	if (fraction == null) bar.removeAttribute('value');
	else bar.value = fraction;
	text.textContent = `${words}…`;
	text.title = fileName ? `Opening ${fileName}` : '';
	// Painted before the next step holds the page. A frame alone is not
	// enough -- it only schedules the paint -- and a tab in the background
	// never gets one, so a timer is the backstop.
	await new Promise((resolve) => {
		const t = setTimeout(resolve, 60);
		requestAnimationFrame(() => setTimeout(() => { clearTimeout(t); resolve(); }, 0));
	});
}

/** The open is over: the bar goes, unless a run has taken it. */
function endOpening() {
	const bar = $('#progress');
	if (!bar?.hasAttribute('data-opening')) return;
	bar.removeAttribute('data-opening');
	if (state.running) return;
	$('#run-progress').classList.remove('is-on');
	bar.value = 0;
	$('#progress-pct').textContent = '';
	$('#progress-pct').title = '';
}

/**
 * Puts a saved run back on screen.
 *
 * Through the worker, and through the same `done` the solver's own answer
 * arrives on -- so what lands is a live run, not a picture of one: the chart
 * asks for its columns the usual way, the table exports, the reader opens, and
 * a series nobody has looked at yet is worked out when they do.
 *
 * `setModel` has just cleared the results and moved the revision, so the run id
 * is taken here, after it.
 */
function openDataset(data, fileName) {
	if (!workerAvailable()) {
		flash(`${fileName} carries a saved run, which needs the simulation worker `
			+ 'this browser is not using. The model opened without it.', 'warn');
		return;
	}
	setRunning(true);
	state.runId += 1;
	state.runRev = state.rev;
	state.runSolver = data.meta?.stats?.solver ?? null;
	// Nothing was integrated, so there is no fingerprint to compare a later
	// edit against: the next edit re-solves rather than re-evaluating somebody
	// else's states under this model's name.
	state.runKey = null;
	state.reusing = false;
	ensureWorker().postMessage({
		type: 'open-dataset', id: state.runId, project: state.raw, data,
	});
}

/**
 * Dropping a model file anywhere on the page opens it.
 *
 * The counter is not decoration: dragging across the page fires dragenter and
 * dragleave for every element passed over, so tracking depth is what stops the
 * hint from flickering on and off as the cursor crosses the diagram.
 */
function setUpFileDrop() {
	const zone = $('#drop-zone');
	let depth = 0;

	// A drag carrying no files is someone selecting text, or the browser's own
	// image drag. It is not an offer to open a model.
	const hasFiles = (ev) => [...(ev.dataTransfer?.types ?? [])].includes('Files');

	const show = (on) => {
		depth = on ? depth : 0;
		zone.hidden = !on;
	};

	window.addEventListener('dragenter', (ev) => {
		if (!hasFiles(ev)) return;
		ev.preventDefault();
		depth++;
		zone.hidden = false;
	});

	window.addEventListener('dragover', (ev) => {
		if (!hasFiles(ev)) return;
		// Without this the browser handles the drop itself -- it navigates to
		// the file, and the page is gone.
		ev.preventDefault();
		ev.dataTransfer.dropEffect = 'copy';
	});

	window.addEventListener('dragleave', (ev) => {
		if (!hasFiles(ev)) return;
		depth = Math.max(0, depth - 1);
		if (depth === 0) show(false);
	});

	window.addEventListener('drop', (ev) => {
		if (!hasFiles(ev)) return;
		ev.preventDefault();
		show(false);
		const files = [...(ev.dataTransfer?.files ?? [])];
		if (!files.length) return;
		openModelFile(files[0]);
		if (files.length > 1) {
			flash(`Opened ${files[0].name}; a drop takes one model at a time.`, 'warn');
		}
	});
}

/**
 * The report matters more than the model: an import that quietly dropped ten
 * block types would look like a working model that gives the wrong answer.
 */
function showImportReport(report, fileName) {
	const box = $('#import-report');
	box.replaceChildren();

	const heading = el('div', { className: 'ir-head' },
		el('b', {}, `Imported ${fileName}`));
	const close = el('button', { className: 'ghost ir-close', type: 'button' }, 'Dismiss');
	close.addEventListener('click', () => { box.hidden = true; });
	heading.append(close);
	box.append(heading);

	box.append(el('p', { className: 'ir-counts' }, report.summary().split('\n')[0]));

	if (report.skipped.length) {
		const byType = new Map();
		for (const sk of report.skipped) {
			if (!byType.has(sk.type)) byType.set(sk.type, []);
			byType.get(sk.type).push(sk.name);
		}
		const list = el('ul', { className: 'ir-list' });
		for (const [type, names] of byType) {
			list.append(el('li', {},
				el('b', {}, `${names.length} ${type}`),
				`: ${names.slice(0, 6).join(', ')}${names.length > 6 ? '…' : ''}`));
		}
		box.append(
			el('p', { className: 'ir-warn' },
				'These blocks have no equivalent in this tool and were left out. '
				+ 'The model will run, but it is not the model you had:'),
			list,
		);
	}

	if (report.renamed.length) {
		box.append(el('details', { className: 'ir-details' },
			el('summary', {}, `${report.renamed.length} block(s) renamed`),
			el('p', { className: 'ir-hint' },
				report.renamed.map((r) => `${r.from} → ${r.to}`).join(', '))));
	}

	// Not a loss: these came across whole and are switched off, which is what
	// the file says about them. Listed because a block that is drawn faded
	// and takes no part in the run is worth knowing about before the numbers
	// are read.
	if (report.disabled.length) {
		box.append(el('details', { className: 'ir-details' },
			el('summary', {},
				`${report.disabled.length} block(s) disabled, as in Ecolego`),
			el('p', { className: 'ir-hint' },
				'Kept in the model and left out of the run. Right-click one to '
				+ 'enable it'
				+ (report.disabledSystems?.size
					? `; ${[...report.disabledSystems].map(([path, n]) => `${n} of them are `
						+ `inside the sub-system '${path}', which the file switches off as a `
						+ 'whole').join(', ')}`
					: '')
				+ ': ' + report.disabled.join(', '))));
	}

	for (const w of report.warnings) {
		box.append(el('p', { className: 'ir-warn' }, w));
	}

	box.hidden = false;
	selectTab('build');
}

/**
 * An export written: said, and its report shown.
 *
 * Not `noteSaved`: the model is not in that file -- it is in its own, and the
 * export is a translation of it that leaves things out -- so the Save button
 * keeps pointing where it pointed, and says there is unsaved work if there is.
 */
function exportedFile(file, fileName) {
	const kB = Math.round(file.body.length / 1024).toLocaleString();
	const lost = file.report.skipped.length;
	flash(`Exported ${fileName} — ${kB} kB`
		+ (lost ? `; ${lost} thing${lost === 1 ? '' : 's'} it has no place for, listed on the Build tab.` : '.'),
	lost ? 'warn' : 'info');
	showExportReport(file.report, fileName);
}

/**
 * What an export could not carry, shown where an import's report is and in
 * the same form: what went out, what was left out and why, what was written
 * in another form, and anything else worth knowing before the file is used.
 */
function showExportReport(report, fileName) {
	const box = $('#import-report');
	box.replaceChildren();

	const heading = el('div', { className: 'ir-head' }, el('b', {}, `Exported ${fileName}`));
	const close = el('button', { className: 'ghost ir-close', type: 'button' }, 'Dismiss');
	close.addEventListener('click', () => { box.hidden = true; });
	heading.append(close);
	box.append(heading);
	box.append(...exportReportNodes(report, { when: 'after', limit: 6, reveal: revealByName }));

	box.hidden = false;
	selectTab('build');
}

/**
 * What a name in a report does when clicked: the block it names, selected on
 * its diagram -- for the names that are blocks of the model as it is now.
 */
const revealByName = {
	has: (name) => !!ed.findBlock(state.raw, name),
	go: (name) => {
		const found = ed.findBlock(state.raw, name);
		if (!found) return;
		closeAllModals();
		selectTab('build');
		setSelection({ kind: found.kind, name });
	},
};

// --- JSON tab -------------------------------------------------------------------

/**
 * Past this many characters the document is offered rather than laid out.
 *
 * Measured in this browser on model F: 48.5 MB of indented JSON, 890
 * thousand lines, **five seconds** of layout before the tab can be used -- and
 * the serialising itself is a fifth of a second of that, so there is nothing
 * to optimise in the writing. A textarea is a single laid-out text node; the
 * cost is the browser's, and the only way not to pay it is not to ask.
 *
 * Four megabytes is about seventy thousand lines, which lays out in half a
 * second. Above it the tab says what the document is and offers to show it.
 */
const HUGE_JSON = 4e6;

/** What the textarea holds, so coming back to the tab does not lay it out again. */
const modelEditor = { rev: -1, text: null, opened: false };

/** The box's colouring, its check and Apply's state: see ./jsoneditor.js. Wired at boot. */
let jsonEd = null;

function renderModelEditor({ force = false } = {}) {
	const ta = $('#json');
	const notice = $('#json-huge');
	// Do not fight the typist -- except on Apply, where rewriting the text is
	// the point: what the model does with an edit is not always what was
	// typed. Derived units are re-derived and shorthands are materialised, and
	// leaving the old text on screen hides that.
	if (!force && document.activeElement === ta) return;
	// Already showing this revision. Every visit to the tab used to re-serialise
	// and re-lay-out the same text, which on a large model is seconds for a
	// document that has not changed.
	if (!force && modelEditor.rev === state.rev && modelEditor.text !== null) return;

	const text = JSON.stringify(state.raw, null, 2);
	modelEditor.rev = state.rev;
	modelEditor.text = text;
	if (force) modelEditor.opened = true;

	if (text.length <= HUGE_JSON || modelEditor.opened) {
		if (notice) notice.hidden = true;
		ta.hidden = false;
		$('#json-box').hidden = false;
		ta.value = text;
		// The text is the model again: nothing edited, nothing to apply.
		jsonEd?.reset();
		return;
	}

	// Too large to lay out. Say what it is, and offer the two things somebody
	// on this tab actually wants: to look at it, or to have the file.
	ta.hidden = true;
	$('#json-box').hidden = true;
	ta.value = '';
	jsonEd?.reset();
	if (!notice) { ta.hidden = false; $('#json-box').hidden = false; ta.value = text; jsonEd?.reset(); return; }
	notice.hidden = false;
	// A number rather than "several seconds": measured at about a quarter of a
	// second per megabyte in this browser, which is the only figure anybody can
	// act on. Rounded hard, because it is an estimate and reads as one.
	const seconds = Math.max(2, Math.round((text.length / 1e6) * 0.27));
	notice.replaceChildren(
		el('b', {}, `${(text.length / 1e6).toFixed(1)} MB of JSON`),
		`, about ${Math.round(text.length / 55).toLocaleString()} lines. Laying that `
		+ `out in an editable box takes this browser roughly ${seconds} seconds, and `
		+ 'the tab cannot be used while it does — so it is not done unless you ask. '
		+ 'Everything else about the model works normally meanwhile. ',
	);
	const show = el('button', { className: 'primary', type: 'button' }, 'Show it anyway');
	show.addEventListener('click', () => {
		modelEditor.opened = true;
		renderModelEditor({ force: true });
	});
	const save = el('button', { type: 'button' }, 'Save it to a file');
	save.addEventListener('click', () => saveFile('json'));
	notice.append(show, ' ', save);
}

function applyModelEditor() {
	// The box is empty because the document was too large to lay out and has
	// not been asked for. Parsing it would report a JSON error about text the
	// user never saw.
	if ($('#json').hidden) {
		flash('The project file is not shown, so there is nothing here to apply. '
			+ 'Press “Show it anyway” first.', 'warn');
		return;
	}
	let parsed;
	try {
		parsed = ed.migrateKeys(JSON.parse($('#json').value));
	} catch (e) {
		showError({ name: 'JSON', message: e.message });
		return;
	}
	try {
		new Project(structuredClone(parsed));
	} catch (e) {
		showError({ name: e.name, message: e.message, blockName: e.blockName });
		return;
	}
	clearError();
	state.raw = parsed;
	state.selection = null;
	state.picked = [];
	// A new model, so results from the old one are not this model's. Without
	// this the chart went on showing the previous model's curves, with nothing
	// on it saying so, because staleness is decided by this counter.
	state.rev += 1;
	// Nor is the picker's list of lines, or the filter over it: what was
	// pasted may be a different model altogether, and its old picker stood
	// there until the new run finished, with the old curves shown again the
	// moment the new run started. The lines that were charted are remembered
	// by name (`prevLabels`) and come back where the names still exist.
	state.results = null;
	state.pickOpen = null;
	clearResultsViews();
	ed.materialiseShorthand(state.raw);
	// A pasted model can carry blocks with no position and view flags of its
	// own; without these, new blocks pile up at the origin and the diagram
	// toggles describe the model that was replaced.
	ed.syncDerivedUnits(state.raw);
	ed.autoLayout(state.raw);
	// One step, whatever was typed into it: the text is not the model until
	// Apply, and this is that moment. Named rather than described, because a
	// hand-edited model can differ from the one before it in every way at
	// once and "Add 4 blocks" would be a third of the truth.
	undoStack.record(state.raw, viewNow(), { label: 'Apply the edited JSON' });
	renderEditorViews();
	renderModelEditor({ force: true });
	renderUndoButtons();
	// Scanned before it is run: a file may arrive with a broken equation in
	// it, and the strip has to say so rather than the run failing twice.
	rescanProblems();
	// Run as any other edit is: when auto-run is on, and only once all of the
	// above has made the text the model. The button used to be "Apply & run"
	// and ran whatever the switch said, which made the one way to edit the
	// whole model at once the one edit that could not be made without paying
	// for a solve.
	if (state.autoRun) runSimulation();
	else renderStaleness();
}

// --- loading ---------------------------------------------------------------

async function loadExample(file) {
	const res = await fetch(new URL(`../../examples/${file}`, import.meta.url));
	if (!res.ok) throw new Error(`Could not load ${file} (${res.status})`);
	setModel(await res.json(), { example: file });
}

/**
 * Where the model in front of you came from, for the picker in the header.
 *
 * `{ example: file }` for one of the bundled ones, `{ label }` for anything
 * else. Kept because a load that fails replaces nothing: the picker has to go
 * back to naming what is still there, and the `change` event has already
 * moved it on by the time we find out.
 */
const UNTITLED = 'Untitled model';
let modelSource = { label: UNTITLED };

/**
 * Points the picker at the model that is actually loaded.
 *
 * The picker lists the examples, and it used to be written to only when one
 * was chosen from it -- so New, Open... and a dropped file each left it naming
 * the example before them. It read as a label on the model, which is exactly
 * how it was being used: over a blank model or an imported .eco it claimed the
 * four-compartment test model, and the one way back to that example -- picking
 * the entry already showing -- fires no `change` at all.
 *
 * Anything that is not an example gets an entry of its own at the top of the
 * list, disabled because it is a statement about what is loaded and not
 * somewhere to load from.
 */
function noteModelSource(source = { label: UNTITLED }) {
	modelSource = source;
	const sel = $('#example');
	if (!sel) return;
	const own = $('#model-source');
	if (source.example) {
		// Back on an example: the list holds it already, and the extra entry
		// would go on offering a model that has been replaced.
		own?.remove();
		sel.value = source.example;
		return;
	}
	const label = source.label ?? UNTITLED;
	const opt = own ?? el('option', { id: 'model-source', value: '', disabled: true });
	opt.textContent = shortName(label);
	// The whole of it, for the name that had to be cut to fit.
	opt.title = label;
	if (!own) sel.prepend(opt);
	sel.value = '';
}

/**
 * A file name cut down to the width the picker already has.
 *
 * A `<select>` is as wide as its widest option and clips without an ellipsis
 * (see the note above `.field select` in app.css), so a long file name would
 * either push the rest of the toolbar around or be cut mid-word. The extension
 * is the part worth keeping: it says which of the three forms was opened.
 */
function shortName(name, max = 30) {
	const s = String(name);
	if (s.length <= max) return s;
	const dot = s.lastIndexOf('.');
	const ext = dot > 0 && s.length - dot <= 5 ? s.slice(dot) : '';
	return `${s.slice(0, Math.max(1, max - ext.length - 1))}…${ext}`;
}

/**
 * Replaces the model in the editor.
 *
 * Every route in comes through here -- an example, a file, a drop, New, the
 * `?model=` parameter -- which is why `source` is asked for here rather than
 * at each of them: see noteModelSource.
 */
function setModel(raw, source) {
	const box = $('#import-report');
	if (box) box.hidden = true;
	noteModelSource(source);
	// A new model opens at its top level, whatever the last one was showing.
	graph?.setSystem('');
	// An older file spells its keys in camelCase. Rename them here, on the way
	// in, so the editor -- and the JSON tab -- only ever show one spelling.
	raw = ed.migrateKeys(raw);
	ed.materialiseShorthand(raw);
	state.raw = raw;
	// A new document is a new revision. Everything that caches anything about
	// the model is keyed on this counter -- the generated Jacobian and its
	// check on the page, the built system the worker keeps for them -- and
	// opening a file used to leave it alone, so those caches went on answering
	// for the model that had just been closed. The rest of this function
	// clears what it knows about by hand; the counter is what covers the rest.
	state.rev += 1;
	// A model with no results is not up to date, whatever the last one was.
	// `dirty` means "there is a run owing", and nothing owes a run more than a
	// model that has never had one -- it is what puts the dot on Run, and what
	// switching auto-run on asks before deciding whether to start.
	state.dirty = true;
	// Which lines the chart draws through a sample, back to this model's own
	// default: the median always, and the mean where the file asks for it.
	state.chartLines = { median: true, mean: !!state.raw?.simulation?.show_mean, single: false };
	// A different model is not the file the last one was in. Opening one *from*
	// a file does not hand the page a writable handle either -- a drop and an
	// `<input type=file>` both give a File and nothing to write back through --
	// so the first Save after opening asks once, and every one after that
	// writes.
	state.fileHandle = null;
	// Nothing to write yet: a model that has just been opened is the model in
	// the file it came from, and a "you have unsaved changes" dot over work
	// nobody has touched is a dot that means nothing. The first edit moves the
	// revision past this and the mark appears.
	state.savedRev = state.rev;
	// A different model is a different document: having asked to lay out one
	// large one is not asking for the next.
	modelEditor.opened = false;
	modelEditor.text = null;
	state.results = null;
	state.selected = [];
	state.prevLabels = null;
	state.selection = null;
	// The scenarios run beside the last model's, and their workers: a
	// different model has its own scenarios, if any, and runs none of them
	// until asked.
	stopScenarios({ all: true });
	state.scenarioChoice = [];
	state.hiddenScenarios.clear();
	// The bands, and the sample they were drawn from. `currentProb` would
	// refuse them anyway once the revision moves, but a model that is *gone*
	// should not leave a megabyte of another model's realisations behind it,
	// nor a worker holding the matrix they came from -- and the belt-and-
	// braces matters here, because every way this is read has at some point
	// been a way it was read wrongly.
	state.prob = null;
	state.probRunning = false;
	state.sensFor = null;
	state.tornado = null;
	state.tornadoRunning = false;
	state.gsa = null;
	state.gsaRunning = false;
	// The fingerprint of the last run's model: a different file is never a
	// re-evaluation of this one, whatever the two happen to hash to.
	state.integrationKey = null;
	state.runKey = null;
	// The multiple selection too. It is reconciled against the new model by
	// name, so blocks that happened to share a name with the last model's
	// arrived already selected -- and Del acted on them.
	state.picked = [];
	state.lastSolveMs = 0;
	// The chart's filter is about the model that has just been closed. Its
	// kind and index chips are ticked by *name*, and a name that means
	// something in one model usually means nothing in the next -- so a filter
	// carried across showed an empty picker for a model with plenty in it,
	// with the chip that emptied it scrolled out of sight above.
	state.pick.query = '';
	state.pick.kinds.clear();
	state.pick.indices.clear();
	state.pick.sample = false;
	state.pickOpen = null;
	state.pickChips = MAX_PICK_CHIPS;
	state.tableRows = TABLE_ROWS;
	// And what the chart pane shows is about that model too. It was left as
	// it stood until the new model's run finished, which on a model that
	// takes a minute to solve was a minute of the old model's picker, filter
	// and legend under the new model's name.
	clearResultsViews();
	// Which sub-systems were unfolded is a fact about the model just closed.
	state.matrixOpen.clear();
	// All of them: a form over the model just closed has nothing to say about
	// the one arriving, however deep it was stacked.
	closeAllModals();
	state.settingsFor = null;
	state.trail = { seen: [], at: -1, moving: false };
	// The tree opens at the top level again: which sub-systems were open is a
	// fact about the model that has just been closed.
	state.tree.open = new Set(['']);
	ed.syncDerivedUnits(state.raw);
	ed.autoLayout(state.raw);
	// After both, so that the first thing on the stack is the model as it is
	// actually shown: undoing the first edit made to a file must not also take
	// back the tidying that opening it did.
	undoStack.reset(state.raw, viewNow());
	// The model as opened, for the version report: one string, kept until
	// the next file replaces it. The undo stack holds the same information
	// as a chain of diffs, but walking two hundred of them back over a
	// megabyte of model to answer "what have I changed since I opened this"
	// is the wrong price for a question a reviewer asks once a session.
	//
	// The undo stack's own text: it was written a line above from the same
	// model, and a second stringify was 60 ms and another copy of the model
	// in memory on the largest imported assessment.
	state.opened = {
		text: typeof undoStack.cur === 'string' ? undoStack.cur : JSON.stringify(state.raw),
		label: modelSource?.example ? `the example ${modelSource.example}` : (modelSource?.label ?? UNTITLED),
	};
	rememberLocked();
	renderEditorViews();
	// The JSON tab's text only for the JSON tab: laid out indented it is twice
	// the model, and selecting the tab writes it. Opening a large model wrote
	// it for nobody -- 90 ms and 46 MB on that assessment.
	if (state.tab === 'model') renderModelEditor();
	renderUndoButtons();
	renderSaveButton();
	// The pane may not have its final size yet on first paint.
	requestAnimationFrame(() => graph?.fit());
	// Built once, for the values at the start, which is also what finds the
	// faults a scan cannot see: see `noteBuildProblem`. Scheduled, so the
	// order against the scan below does not matter.
	state.buildProblem = null;
	recheckBuild();
	// Same reason as `setModel`: a file, or an example, can arrive with
	// something wrong in it, and the strip is where that is said.
	rescanProblems();
	// Only if the switch says so. Opening a file used to start a solve
	// whatever `auto-run` was set to, which on a model of ten thousand states
	// is half a minute of a page that cannot be stopped doing something
	// nobody asked it for. With the switch off the chart says there are no
	// results yet and offers the button.
	if (state.autoRun) runSimulation();
	else renderStaleness();
	// The model just opened is what this tab is working on now. Written
	// without waiting for an edit: a file opened and then refreshed away
	// would otherwise be offered back as the model before it.
	draftKeeper.note(state.raw, draftMeta());
}


// --- tabs ---------------------------------------------------------------------------

function selectTab(name) {
	state.tab = name;
	for (const t of document.querySelectorAll('.tab')) {
		t.setAttribute('aria-selected', String(t.dataset.tab === name));
	}
	for (const p of document.querySelectorAll('.panel')) {
		p.dataset.active = String(p.id === `panel-${name}`);
	}
	if (name === 'indexlists') renderIndexListsView();
	// Whether the rail is there is `applyPanes`'s to decide -- it depends on
	// this tab *and* on whether the reader has folded it away, and something
	// that set `hidden` here would be undone by the next window resize.
	applyPanes();
	document.body.dataset.tab = name;
	if (name === 'matrix') drawMatrix();
	if (name === 'table' && state.results && tableDirty) {
		drawTable();
		// The staleness notice lives inside the panel the line above rebuilt.
		renderStaleness();
	}
	if (name === 'chart' && state.results) chart?.draw();
	if (name === 'build') graph?.render();
	if (name === 'code') { renderCode(); if (generated.view === 'jacobian') renderJacobian(); }
	if (name === 'model') renderModelEditor();
	if (name === 'help') renderHelp($('#panel-help'));
}

// --- boot -----------------------------------------------------------------------------

export function boot() {
	clearStatus();
	// Which build this is, at the foot of the Help tab.
	setBuildStamp(BUILD);
	// A topic's "Read more in Help" goes to its section of the Guide: any
	// dialog over the page first, since the Help tab is under it.
	setInfoLinks((heading) => {
		closeAllModals();
		selectTab('help');
		goToHelp($('#panel-help'), 'guide', headingId(heading));
	});
	wireFlash();
	wireRailSplit();
	wirePaneSplits();
	chart = new TimeChart($('#chart'));
	graph = new GraphEditor($('#graph'), {
		onChange: modelChanged,
		// The diagram may select several blocks at once, so it says which as
		// well as which one to inspect. `setSelection` is not used here: it
		// would echo the selection straight back to the diagram that just
		// made it.
		onSelect: (sel, picked) => {
			state.selection = sel;
			state.picked = picked ?? (sel?.name ? [sel.name] : []);
			// The trail is about what was being looked at, not about how it
			// was reached, and a click on the diagram is the commonest way of
			// all -- so it belongs in the trail, and was the one route that
			// did not record. `setSelection` is still not called here, for the
			// reason above it: it would echo the selection straight back to
			// the diagram that just made it.
			recordVisit(sel?.name ?? null);
			renderBreadcrumb();
			renderRail();
			renderMatrixView();
		},
		onStatus: flash,
		// Walking into a sub-system is not an edit either, and for the same
		// reason it is where the next step back should return to.
		onSystem: () => {
			undoStack.note(viewNow());
			renderBreadcrumb();
			renderRail();
			// Information follows the diagram in when nothing is selected.
			if (!state.selection) renderInfoCard();
		},
		// Renaming a sub-system is the one graph action that needs a word from
		// the user; everything else is a menu pick or a drag.
		onPrompt: (question, initial) => window.prompt(question, initial),
		// The same question with room to answer it in lines. A sticky note is
		// written in them, and `window.prompt` holds one line however long the
		// note is.
		/**
		 * A shape's settings, from a double-click or from its menu.
		 *
		 * The dialog is given a way to read the shape and a way to change it
		 * rather than the shape itself: it stays open while the canvas behind
		 * it changes, so what it shows has to come from the model each time.
		 */
		onShapeSettings: ({ ids, read, apply }) => {
			openShapeSettings({ read, count: ids.length, onChange: apply });
		},
		onPromptLines: (question, initial, then) => {
			let box;
			const modal = openModal({
				title: question,
				subtitle: 'Lines are kept as you type them; the words between them wrap to the shape',
				build: (body) => {
					box = el('textarea', {
						className: 'shape-label', rows: 5, spellcheck: false, value: initial ?? '',
					});
					body.append(box);
					const done = el('button', { type: 'button', className: 'primary' }, 'Set');
					done.addEventListener('click', () => { modal.close(); then(box.value); });
					const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
					cancel.addEventListener('click', () => modal.close());
					// Enter is a newline here, so the keyboard way out is the
					// one a textarea leaves free.
					box.addEventListener('keydown', (ev) => {
						if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) {
							ev.preventDefault();
							modal.close();
							then(box.value);
						}
					});
					body.append(el('div', { className: 'pdf-foot' },
						el('span', { className: 'pdf-note' }, 'Ctrl or \u2318 with Enter sets it.'),
						cancel, done));
				},
			});
			requestAnimationFrame(() => { box?.focus(); box?.select(); });
		},
		// Deleting a sub-system takes everything inside it in one go. Undo
		// brings it back, but a question first is cheaper than working out
		// afterwards what went -- the one edit here that asks.
		onConfirm: (question) => window.confirm(question),
		onOpenSettings: openBlockSettings,
		// Putting the canvas in front, for the menu items that act on it.
		// These menus open from the tree and the Information view as well, and
		// both of those are beside every tab -- so `Centre on the canvas`,
		// picked from the tree with the chart in view, has to bring the canvas
		// with it or it centres something nobody can see. The graph does the
		// centring and knows nothing about tabs.
		onShowDiagram: () => { if (state.tab !== 'build') selectTab('build'); },
		// The clipboard is the application's, not the diagram's: the block
		// tree offers the same three items, and two clipboards that disagree
		// about what was copied would be worse than none.
		onCut: cutSelection,
		onCopy: copySelection,
		onPaste: pasteClipboard,
		// And a block's look, with a clipboard of its own.
		formatClipboard: () => state.formatClip,
		onCopyFormat: copyFormat,
		onPasteFormat: pasteFormat,
		// The chart or the table, whichever is the tab in view -- they draw the
		// same choice of series, so one action serves both and only the word
		// changes. The diagram is on a different tab from either, so in
		// practice these items are the tree's and the Information view's.
		seriesView: () => (state.results
			&& (state.tab === 'chart' || state.tab === 'table') ? state.tab : null),
		onChart: (names, mode) => chartBlocks(names, mode),
		onImport: () => pickFile(importFromFile),
		clipboard: clipboardInfo,
	}, {
		// The wheel is taken across the whole tab, not only over the canvas:
		// the canvas has a frame around it -- the panel's padding, the
		// breadcrumb above, the help line below -- and a wheel there did
		// nothing, which reads as a zoom that only works over blocks. Nothing
		// in this panel scrolls (`#panel-build` is `overflow: hidden`), so
		// there is nothing else for a wheel here to mean.
		wheelHost: $('#panel-build'),
	});

	const sel = $('#example');
	// The examples in a group of their own, so the entry that names a model
	// from somewhere else reads as apart from them rather than as one more
	// example of ours. See noteModelSource.
	const examples = el('optgroup', { label: 'Examples' });
	for (const ex of EXAMPLES) examples.append(el('option', { value: ex.file }, ex.title));
	sel.append(examples);
	sel.addEventListener('change', () => loadExample(sel.value).catch((e) => {
		// Nothing was replaced, so the picker goes back to naming what is
		// still loaded instead of the example that never arrived.
		noteModelSource(modelSource);
		showError({ name: 'Load', message: e.message });
	}));

	$('#run').addEventListener('click', () => runSimulation({ manual: true }));
	$('#cancel').addEventListener('click', cancelSimulation);
	$('#open').addEventListener('click', openFile);
	// One door in: the file is read, then what it holds is offered — a model
	// to open or to take blocks from, a run saved beside it, or data. Which of
	// those somebody wants is not a thing the extension can answer.
	$('#import').addEventListener('click', () => pickFile(chooseImport));
	setUpFileDrop();
	// A plain click saves as JSON, which is what most saves are.
	// The button opens the room where what and how are chosen. ⌘S still writes
	// straight to the file this model came from -- pressing a key called Save
	// should save, and a dialog between the key and the file would be one more
	// thing between a reader and the thing they asked for.
	$('#save').addEventListener('click', () => openSave());

	// Right-clicking it does the same: that is where a hand goes looking for
	// "the other way to do this", and now there is only the one way.
	$('#save').addEventListener('contextmenu', (ev) => { ev.preventDefault(); openSave(); });
	$('#new').addEventListener('click', () => setModel(blankModel(), { label: 'New model' }));
	// The table's own menu carries the export; there is no toolbar button.
	$('#panel-table').addEventListener('contextmenu', tableMenu);
	$('#table-mode').addEventListener('change', (ev) => {
		state.tableMode = ev.currentTarget.value === 'at' ? 'at' : 'time';
		state.tableRows = TABLE_ROWS;
		tableDirty = true;
		drawTable();
		renderTableMode();
	});
	$('#table-series').addEventListener('change', (ev) => {
		state.tableSeries = ev.currentTarget.value;
		tableDirty = true;
		drawTable();
	});
	$('#table-real').addEventListener('input', (ev) => {
		const n = Math.round(Number(ev.currentTarget.value));
		const most = currentProb()?.iterations ?? 1;
		// One-based on screen, because "realisation 734" is what the rest of
		// the tool calls it; zero-based underneath, where the matrix is.
		if (!Number.isFinite(n)) return;
		state.tableReal = Math.min(most - 1, Math.max(0, n - 1));
		tableDirty = true;
		drawTable();
	});
	$('#table-at').addEventListener('change', (ev) => {
		state.chartAt = Number(ev.currentTarget.value);
		tableDirty = true;
		drawTable();
		renderChart();
	});
	$('#chart-mode').addEventListener('change', (ev) => {
		const want = ev.currentTarget.value;
		state.chartMode = want === 'dist' || want === 'scatter' ? want : 'time';
		renderChart();
		renderRunKind();
		renderStaleness();
	});
	$('#chart-at').addEventListener('change', (ev) => {
		state.chartAt = Number(ev.currentTarget.value);
		renderChart();
	});
	$('#chart-bins').addEventListener('input', (ev) => {
		const raw = ev.currentTarget.value.trim();
		const n = Math.round(Number(raw));
		// Empty is "use the rule", and a number outside what a histogram can
		// be asked for is nothing at all rather than a silently clamped
		// something: the box says its own limits.
		state.histBins = raw === '' || !Number.isFinite(n) || n < HIST_BINS.min
			? null
			: Math.min(HIST_BINS.max, n);
		renderChart();
	});
	$('#chart-binscale').addEventListener('change', (ev) => {
		state.histScale = ev.currentTarget.value;
		renderChart();
		renderChartMode();
	});
	$('#chart-x').addEventListener('change', (ev) => {
		state.scatterX = ev.currentTarget.value || null;
		renderChart();
	});
	for (const id of ['#chart-discard', '#table-discard']) {
		$(id)?.addEventListener('click', () => discardProb());
	}
	$('#chart-lines').addEventListener('change', (ev) => {
		const box = ev.target.closest('input[data-line]');
		if (!box) return;
		state.chartLines = { ...state.chartLines, [box.dataset.line]: box.checked };
		renderChart();
		renderRunKind();
		// Which box is now the last one on, and so cannot be turned off.
		renderChartMode();
	});
	$('#chart-spread').addEventListener('change', (ev) => {
		state.chartSpread = ev.currentTarget.value;
		renderChart();
		renderRunKind();
	});
	$('#apply').addEventListener('click', applyModelEditor);
	jsonEd = wireJsonEditor({
		ta: $('#json'),
		box: $('#json-box'),
		hl: $('#json-hl'),
		toggle: $('#json-syntax'),
		status: $('#json-check'),
		apply: $('#apply'),
		baseline: () => modelEditor.text,
		// What Apply would refuse, and nothing more: a model with a broken
		// equation in it is still a model, and the strip says what is wrong
		// with it once it is applied. See applyModelEditor.
		validate: (parsed) => { new Project(ed.migrateKeys(parsed)); },
	});
	$('#json-tools').append(infoButton('panel:json', () => panelTopic('json')));
	for (const b of document.querySelectorAll('[data-codeview]')) {
		b.addEventListener('click', () => showGeneratedView(b.dataset.codeview));
	}

	// The name and description are shown in the header; clicking either goes
	// to the field that edits it, which is where people look first.
	for (const [sel, target] of [['#title', '#model-name'],
		['#subtitle', '#model-description']]) {
		const n = $(sel);
		n.addEventListener('click', () => {
			// The field has to be there to take the caret: the panel may be
			// folded away, and the Model section starts closed -- a field
			// inside a closed <details> cannot take focus either.
			revealPane('left');
			openSection('model');
			const field = $(target);
			if (!field) return;
			field.scrollIntoView({ block: 'nearest' });
			field.focus();
			// A name is usually replaced wholesale; a description is added to.
			if (field.tagName === 'INPUT') field.select();
			else field.setSelectionRange(field.value.length, field.value.length);
		});
	}

	// A tab list answers to the arrow keys, which is what `role="tablist"`
	// promises a screen reader: Left and Right move between the tabs, Home
	// and End go to the ends, and each tab names the panel it controls.
	const tablist = document.querySelector('.tabs[role="tablist"]');
	if (tablist) {
		const tabs = [...tablist.querySelectorAll('.tab')];
		for (const t of tabs) t.setAttribute('aria-controls', `panel-${t.dataset.tab}`);
		tablist.addEventListener('keydown', (ev) => {
			const at = tabs.indexOf(document.activeElement);
			if (at < 0) return;
			const step = { ArrowRight: 1, ArrowLeft: -1, Home: -at, End: tabs.length - 1 - at }[ev.key];
			if (step === undefined) return;
			ev.preventDefault();
			const next = tabs[(at + step + tabs.length) % tabs.length];
			next.focus();
			selectTab(next.dataset.tab);
		});
	}

	$('#autorun').addEventListener('change', (e) => {
		state.autoRun = e.target.checked;
		// Switching it on is asking for the model to be kept up to date, and
		// the first thing that means is *now* -- otherwise the switch appears
		// to do nothing until something else is edited, which on a model that
		// has never run is the whole time somebody is waiting.
		// Not `manual`: that is the Run button, and the Run button means "show
		// me this one run", which takes the tab off a sample's picture. Ticking
		// auto-run is not asking for that.
		if (state.autoRun && (state.dirty || !state.results)) runSimulation();
	});

	// The Build panel's controls -- adding blocks, what the diagram shows,
	// auto-layout, fit, zoom -- live in the diagram's own right-click menu:
	// see GraphEditor._canvasMenu.

	// The chart's own settings are on its own menu, the way the diagram's are:
	// two checkboxes above a chart are two checkboxes in the way of it the rest
	// of the time, and a picture of the chart has nowhere else to be asked for.
	$('#chart-shell').addEventListener('contextmenu', chartMenu);

	for (const t of document.querySelectorAll('.tab')) {
		t.addEventListener('click', () => selectTab(t.dataset.tab));
	}

	// The way back to a list that has been put away. It takes the model with
	// it -- the switch is saved under `view` -- and re-renders through the
	// same path the Hide button does.
	$('#warnings').addEventListener('click', () => {
		ed.setView(state.raw, { show_warning_list: true });
		state.problemsExpanded = false;
		modelChanged({ layoutOnly: true });
	});

	$('#theme').addEventListener('click', () => {
		const cur = document.documentElement.getAttribute('data-theme');
		const next = cur === 'dark' ? 'light' : cur === 'light' ? null : 'dark';
		if (next) document.documentElement.setAttribute('data-theme', next);
		else document.documentElement.removeAttribute('data-theme');
		themeChanged();
	});

	// The third state of that button is *system*, which is not a snapshot: the
	// operating system can change scheme while the page is open. Nothing was
	// listening, so a canvas painted in the dark stayed dark until something
	// else happened to redraw it.
	globalThis.matchMedia?.('(prefers-color-scheme: dark)')
		?.addEventListener?.('change', () => {
			if (!document.documentElement.hasAttribute('data-theme')) themeChanged();
		});

	// Framed in a page that has a light/dark switch of its own -- see
	// `?chrome=` in ./start.js, which also hides the button above -- the
	// switch is over there and has to reach in. A message rather than a
	// reload of this frame: what is in here is somebody's unsaved model.
	//
	// Only from the window that framed this one, only same-origin, and only
	// the two words: a theme is the whole of what an embedder may say.
	window.addEventListener('message', (ev) => {
		if (ev.origin !== location.origin || ev.source !== window.parent) return;
		if (ev.data?.type !== 'kvot:theme') return;
		const theme = ev.data.theme;
		if (theme !== 'light' && theme !== 'dark') return;
		if (document.documentElement.getAttribute('data-theme') === theme) return;
		document.documentElement.setAttribute('data-theme', theme);
		themeChanged();
	});

	$('#undo').addEventListener('click', () => timeTravel(true));
	$('#redo').addEventListener('click', () => timeTravel(false));

	window.addEventListener('keydown', (e) => {
		if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
			e.preventDefault();
			runSimulation({ manual: true });
			return;
		}
		// Save, as everywhere: ⌘S writes it, ⇧⌘S asks where. Taken before the
		// modifier check below, which lets shift through to the other
		// shortcuts but not past this one.
		if ((e.metaKey || e.ctrlKey) && !e.altKey && (e.key === 's' || e.key === 'S')) {
			e.preventDefault();
			if (e.shiftKey) saveFile('json');
			else saveToFile();
			return;
		}
		if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
		const key = e.key.toLowerCase();
		if (key !== 'z' && key !== 'y') return;
		// A field has an undo stack of its own, and it is the one meant by
		// Cmd+Z while typing in it. Ours takes back whole edits; the model has
		// not heard about the half-typed one yet.
		if (isTyping(e.target)) return;
		e.preventDefault();
		timeTravel(key === 'z' && !e.shiftKey);
	});

	// The draft is written a couple of seconds after the typing stops, so a tab
	// closed inside that window would lose the last edit -- which is the edit
	// somebody is most likely to want back. `pagehide` rather than
	// `beforeunload`: it is the one that fires when a tab is discarded or the
	// page goes into the back/forward cache, which are the cases this is for,
	// and it does not ask the browser for permission to run.
	window.addEventListener('pagehide', () => draftKeeper.flush());

	// Another tab copied something. Nothing here has to be re-read -- the
	// menus ask `clipboardInfo` when they open, and that reads the shared
	// record every time -- but a Paste that has quietly become possible is
	// worth one line, because the reader is looking at this window and the
	// copy happened in the other one.
	shared.watch((rec) => {
		if (!rec) return;
		const from = rec.meta?.model;
		flash(`A copy was taken${from ? ` in ${from}` : ' in another tab'}. `
			+ 'Paste puts it here.', 'info');
	});

	// Read before anything opens a model, because opening one writes over it.
	const held = autosave.draft();

	const params = new URLSearchParams(location.search);
	const theme = params.get('theme');
	if (theme === 'light' || theme === 'dark') {
		document.documentElement.setAttribute('data-theme', theme);
	}
	// `decay` was this panel's name before half-lives joined the index lists
	// they belong to. A link written against the old name still works.
	if (params.has('tab')) {
		const want = params.get('tab');
		// One of the tabs there are, or the default: an unknown name left no
		// panel active and the window blank.
		const tab = want === 'decay' ? 'indexlists' : want;
		if ([...document.querySelectorAll('.tab')].some((t) => t.dataset.tab === tab)) selectTab(tab);
	}
	else selectTab('build');

	const wanted = params.get('model');

	/*
	  `?model=draft` is how the model gets out of the page's frame. The "full
	  window" link on kompartment.html sets it, and what it names is the draft
	  this tab has already written -- the two pages are one origin, and the
	  framed one flushes on `pagehide`, which is what leaving it is. So the
	  model that was open comes with, unsaved edits and all.

	  Restored rather than offered, which is the one place that is right: the
	  reader has just said which model they mean by stepping out of the frame
	  with it open, and a bar asking them to confirm it would be the editor
	  pretending not to know.

	  Nothing held means the draft was refused -- storage switched off, or a
	  model past the ceiling in ./autosave.js. Then this falls through to the
	  usual start and says so, because the model silently not arriving is the
	  one failure here the reader would otherwise read as their work being gone.
	*/
	if (wanted === 'draft') {
		if (held?.raw) {
			setModel(held.raw, { label: held.meta?.label || held.raw.name || UNTITLED });
			return;
		}
		flash('The model could not be carried over from the framed page — it was not '
			+ 'being kept, so this is a new model. Nothing is lost: the '
			+ 'other page still has it.', 'warn');
	}

	// A new, empty model -- what New gives -- unless the address names one of
	// the examples. The page is where a model is built, and opening it on one
	// of ours meant clearing that away before starting; the examples are one
	// choice away in the picker at the top. `?model=blank` still says the same
	// thing, for the links that were written when it had to be asked for.
	const start = EXAMPLES.some((e) => e.file === wanted) ? wanted : null;
	if (!start) {
		setModel(blankModel(), { label: 'New model' });
		if (wanted && wanted !== 'blank' && wanted !== 'draft') {
			flash(`There is no example called “${wanted}”, so this is a new model. `
				+ 'The examples are in the list at the top.', 'warn');
		}
		offerDraft(held);
		return;
	}
	// Named before it arrives, so the picker does not show another example on
	// the way to this one. setModel says it again when it lands.
	noteModelSource({ example: start });
	loadExample(start)
		.catch((e) => {
			// Never leave an empty editor: fall back to a blank model so the
			// toolbar still works, and say why the example did not load.
			setModel(blankModel(), { label: 'New model' });
			flash(
				`Could not load the example (${e.message}). Started a blank model instead.`,
				'warn',
			);
		})
		// After the model is on screen either way: the offer sits above the
		// tabs and is about replacing what is there.
		.finally(() => offerDraft(held));
}

/**
 * What this tab was working on when it was last open, offered back.
 *
 * Offered rather than restored. The tab may have been opened deliberately on
 * an example, or on a `?model=` link somebody sent; putting a draft over that
 * without asking would be the editor deciding what the reader meant. So it is
 * one line above the tabs, with the name and how long ago, and it goes as soon
 * as it is answered -- either way, because an offer that survives being
 * declined is a thing to keep declining.
 *
 * Nothing at all when there is no draft, which is the common case: a first
 * visit, a browser that keeps nothing, or a tab that was closed on a model too
 * large to hold.
 */
function offerDraft(held) {
	const bar = $('#draft-offer');
	if (!bar) return;
	if (!held || !held.raw) { bar.hidden = true; return; }
	// Not over the model that is already on screen: opening a file, working on
	// it, and refreshing should not be met with an offer to open the same
	// thing again. `sameModel` does the cheap half of that comparison first,
	// so a 35 MB assessment is not serialised on every cold start.
	if (autosave.sameModel(held.raw, state.raw)) { bar.hidden = true; return; }
	const done = () => { bar.replaceChildren(); bar.hidden = true; };
	const restore = el('button', { type: 'button', className: 'primary' }, 'Restore');
	restore.addEventListener('click', () => {
		done();
		const source = { label: held.meta?.label || held.raw.name || UNTITLED };
		setModel(held.raw, source);
		flash('Restored what this tab was working on. It was never saved to a '
			+ 'file — use Save… for that.', 'info');
	});
	const no = el('button', { type: 'button', className: 'ghost' }, 'Discard');
	no.addEventListener('click', () => { done(); autosave.forget(); });
	bar.replaceChildren(
		el('span', { className: 'draft-what' },
			'This tab was working on ',
			el('b', {}, shortName(held.meta?.label || held.raw.name || UNTITLED)),
			' ',
			el('span', { className: 'draft-when' }, autosave.howLongAgo(held.at)),
			'. It was not saved to a file.'),
		restore, no);
	bar.hidden = false;
}
