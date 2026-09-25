/**
 * What each dialog is for, for the (i) in its title bar (./infopanel.js).
 *
 * A dialog passes `info: dialogInfo('probabilistic')` to `openModal`; this is
 * where what it says is kept, one topic per dialog, each a summary of the
 * Guide section it links to at its foot. The block settings windows have
 * theirs in ./blockinfo.js, one per kind of block.
 */

const KICKER = 'Dialog';

/** The topics, by dialog. */
const TOPICS = {
	probabilistic: {
		title: 'Probabilistic run',
		lead: 'Integrate the model once per realisation, drawing every distributed input from its '
			+ 'distribution each time, and draw where the outcomes were: a band rather than a curve.',
		sections: [{
			list: [
				'**Realisations**, **Seed** and **Sampling** — how many runs, the number that makes '
				+ 'them repeatable, and Latin hypercube or independent draws. An imported model arrives '
				+ 'with its own.',
				'**Varying** — every distribution in the model, or only some of them, to see what one '
				+ 'input is worth. **Correlate inputs** draws some of them together.',
				'**Keep only the endpoints** — hold the realisations of the model’s endpoints and '
				+ 'nothing else, which is what makes a large run fit. **Choose blocks…** sets the list.',
				'**Cores** — how many workers share the runs; auto is every core but one. The numbers '
				+ 'are the same on one core as on sixteen.',
			],
		}, {
			text: 'It says what the run will cost before it starts — values drawn, series kept, memory, '
				+ 'and a time measured from the run already made — and refuses one that will not fit.',
		}],
		more: 'A probabilistic run',
	},
	replay: {
		title: 'Replay a realisation',
		lead: 'Run one realisation of the probabilistic run again as an ordinary run, every series of it, '
			+ 'in place of the deterministic run on the chart and in the table.',
		sections: [{
			text: 'Give its number, from a table or a category. It is rebuilt from the seed, not read back, '
				+ 'so it is the same to the last digit whether or not the sample is still held. The status '
				+ 'line says which realisation is on screen, and lists what every input was.',
		}],
		more: 'Replaying one realisation',
	},
	bands: {
		title: 'Bands',
		lead: 'Which percentiles the chart’s probabilistic bands are drawn at, and whether the mean is '
			+ 'drawn as well as the median.',
		sections: [{
			text: 'Pairs, outermost faintest: the default is 5–95 behind 25–75. Saved with the model, '
				+ 'as the desktop tools keep their percentile pairs.',
		}],
		more: 'What the lines are, and what is behind them',
	},
	tornado: {
		title: 'Tornado',
		lead: 'Hold every input at the model’s own value, swing one to a low and then a high percentile, '
			+ 'and see what the output does; then the next. Two runs per input and one shared.',
		sections: [{
			list: [
				'**Low percentile** and **High percentile** — where each input is swung to; saved with '
				+ 'the model.',
				'**Cores** — how many workers share the runs, as for a probabilistic run.',
			],
		}, {
			text: 'It needs no sample and finds no interactions: the chart to draw before the distributions '
				+ 'are trusted, or to decide which inputs deserve one.',
		}],
		more: 'Tornado',
	},
	'tornado-result': {
		title: 'Tornado result',
		lead: 'A bar per input, from what the output was with the input low to what it was with it high, '
			+ 'ranked by the swing, with the central value marked.',
		sections: [{
			text: 'A red bar is an input whose high end lowers the output. **Of**, the reading — peak, '
				+ 'end, lowest, at a time — and the time change the answer without running anything '
				+ 'again. Double-click a row to replay that input’s high point in full.',
		}],
		more: 'Tornado',
	},
	gsa: {
		title: 'Global sensitivity',
		lead: 'A designed experiment over the model’s distributions: Morris, Sobol, eFAST, RBD-FAST, a '
			+ 'fractional factorial, DGSM, the radial design or Shapley effects.',
		sections: [{
			text: [
				'Each method answers a different question at a very different price, and the dialog says '
				+ 'what a design will cost before it runs. Screen with Morris or the factorial, then spend '
				+ 'Sobol’s runs on the inputs that survive.',
				'The runs are shared over the cores like a probabilistic run’s.',
			],
		}],
		more: 'Global sensitivity',
	},
	'gsa-result': {
		title: 'Global sensitivity result',
		lead: 'The method’s indices for every input, for the output and the reading chosen.',
		sections: [{
			text: '**Of** and the reading change the answer from the runs already made. Intervals are '
				+ 'shown where the method gives them.',
		}],
		more: 'Global sensitivity',
	},
	dydp: {
		title: 'Sensitivity to one parameter',
		lead: 'At the values the model holds, how much each block moves when one parameter moves: a '
			+ 'derivative integrated with the model, exact, and needing no distributions.',
		sections: [{
			text: 'Tick a few parameters: each adds a copy of the state vector to the solve, and the dialog '
				+ 'says what the total will be. The answer is an elasticity — 1% more of the parameter '
				+ 'gives so many % more of the block — against time, with dy/dp itself in the table.',
		}],
		more: 'Sensitivity to one parameter',
	},
	'dydp-result': {
		title: 'Sensitivity result',
		lead: 'Each chosen parameter’s elasticity on one block across the run, with zero always in view.',
		sections: [{
			text: 'An elasticity of 0.4 means 1% more of the parameter gives 0.4% more of the block, which '
				+ 'compares across a whole model where dy/dp, carrying both units, does not.',
		}],
		more: 'Sensitivity to one parameter',
	},
	'what-drove': {
		title: 'What drove it',
		lead: 'Which sampled inputs one output depends on, from the realisations already run — no '
			+ 'further runs.',
		sections: [{
			list: [
				'**Of** — the output; **At** — a time, where it peaks on average, or each '
				+ 'realisation’s own peak.',
				'**Measures** — the correlations and regression coefficients, or the distribution-based '
				+ 'measures beside the rank correlation; **Translate** reads them on logs or ranks.',
				'**Inputs** — narrow the analysis to some of them.',
			],
		}],
		more: 'What drove the spread',
	},
	'analysis-inputs': {
		title: 'Inputs in the analysis',
		lead: 'Which of the sampled inputs What drove it is about: the table ranks these, the regression is '
			+ 'fitted to these, and the distribution measures are of these.',
		sections: [{
			list: [
				'Two trees, as in Save…: **Left out** on the left, **In the analysis** on the right. Each '
				+ 'has its own search — a name, or a pattern such as `C*_out` — and a kind filter.',
				'Select rows and move them across with **›** and **‹**, or everything a side shows with '
				+ '**»** and **«**. Double-clicking a row, Enter, dragging and the right-click menu move '
				+ 'them too.',
				'**Apply** asks again over the new set, from the realisations already run. At least one '
				+ 'input has to stay in.',
			],
		}, {
			text: 'An indexed parameter is one input per index value, named with it in brackets. The choice '
				+ 'is kept while you change the output and the time: it is about the sample, not about one '
				+ 'series.',
		}],
		more: 'What drove the spread',
	},
	distribution: {
		title: 'Distribution summary',
		lead: 'One output at one time as a distribution: its histogram and cumulative curve, the '
			+ 'statistics, the percentiles, and a calculator between values and probabilities.',
		sections: [{
			list: [
				'**Of**, **At** and **Scale** — which output, when, and on what axis.',
				'A varied parameter is drawn with the distribution it was sampled from.',
				'**Fit** — each shape a parameter can have, fitted by maximum likelihood or by moments '
				+ 'and ranked by a test, any of them drawn over the histogram.',
			],
		}, {
			text: 'The band on the cumulative curve is the DKW 95% band, which holds for any shape.',
		}],
		more: 'The distribution of one output',
	},
	categories: {
		title: 'Categories of realisation',
		lead: 'Sort the realisations by a condition on one series — its peak, its lowest, its end, its '
			+ 'value at a time, against a number — each into the first category it meets.',
		sections: [{
			text: 'Untick **Include** and a category is screened out of everything: the bands, the mean, '
				+ 'What drove it, the distribution summary. The legend says so. The categories are saved '
				+ 'with the model.',
		}],
		more: 'Categories of realisation',
	},
	save: {
		title: 'Save',
		lead: 'Everything this model and its run can be written out as, in one place.',
		sections: [{
			list: [
				'**Model** — the model itself, as a project file; or exported as an `.eco` project, with '
				+ 'a list of what that file has no place for.',
				'**Model with results** — the model and its run in one archive that opens again as it '
				+ 'was; the chosen blocks become the model’s endpoints.',
				'**Results** — any of the series, as CSV or HDF5.',
				'**Realisations** — a probabilistic run’s sample, its mean, or one realisation of it.',
				'**Data** — the parameters and lookup tables, as a spreadsheet or HDF5.',
				'**Run log** — what the run was, as text.',
			],
		}],
		more: 'Saving the results',
	},
	'saved-times': {
		title: 'Saved times',
		lead: 'The series the output times are made of, combined into one set: a geometric one for the '
			+ 'run and an even one for its first year, say, and any times written out by hand.',
		sections: [{
			text: 'A single series cannot describe a hundred thousand years and the first one at once; '
				+ 'several can. A series entirely outside the run saves nothing, and is marked so.',
		}],
		more: 'When results are saved',
	},
	endpoints: {
		title: 'Endpoints',
		lead: 'The blocks whose results a probabilistic run keeps, and a results file carries. Two trees: '
			+ 'the blocks the run produces on the left, the endpoints on the right.',
		sections: [{
			text: 'A block brings every index of it. **Done** saves the list with the model, so the next run '
				+ 'starts where the last one left off; an imported model arrives with its own.',
		}],
		more: 'Choosing endpoints',
	},
	optimise: {
		title: 'Optimise',
		lead: 'Solve for the parameter values that put chosen endpoints at chosen values, between bounds '
			+ 'you set.',
		sections: [{
			list: [
				'**What these should come to** — endpoints, where each is read, the value it should '
				+ 'have, how the miss is measured, and a weight.',
				'**What may vary** — the parameters, each between two bounds.',
				'**Method** — how the search goes.',
			],
		}, {
			text: 'Nothing in the model changes until you ask: the answer can be previewed on the chart first.',
		}],
		more: 'Solving for the inputs',
	},
	'optimise-add': {
		title: 'Add to the list',
		lead: 'Tick the rows to add to the calibration: the endpoints it should match, or the parameters it '
			+ 'may vary. What is on the list already is not offered.',
		sections: [{
			list: [
				'The search box narrows the list as you type. **any kind** and **anywhere** filter it by kind '
				+ 'of block and by sub-system, where there is more than one of either.',
				'**All shown** and **None** tick and untick everything the search and the filters leave — '
				+ 'every far-field path in one go, say.',
				'At most 300 rows are listed at once. The line under the list says how many are ticked, and '
				+ 'when there are more matches than it shows.',
			],
		}, {
			text: '**Add** puts the ticked rows on the list, where their settings are then yours to change: a '
				+ 'parameter starts between a tenth and ten times the value it holds, or a span either side '
				+ 'of it where it is not positive.',
		}],
		more: 'Solving for the inputs',
	},
	query: {
		title: 'Ask the model',
		lead: 'The questions that come up on a model somebody else built: what uses a block, what it needs, '
			+ 'what nothing reads, which blocks are only data, which carry a distribution.',
		sections: [{
			text: 'The answer is pinned over the tree in the left panel until its × is pressed, and can be '
				+ 'searched and filtered like the tree itself.',
		}],
		more: 'Asking the model about itself',
	},
	'distribution-editor': {
		title: 'Distribution',
		lead: 'What a probabilistic run draws this parameter from. A deterministic run uses the value; this '
			+ 'is what a probabilistic one samples.',
		sections: [{
			list: [
				'**Shape** — uniform, triangular, normal, their log forms, a log-normal given three ways, or '
				+ 'a list of **Values** taken one per realisation.',
				'**Truncation** — cut the curve at values, or at percentiles of itself.',
			],
		}, {
			text: 'The curve is drawn as you type, and a distribution that cannot be sampled says why.',
		}],
		more: 'A distribution on a parameter',
	},
	nuclides: {
		title: 'Choose nuclides from ICRP 107',
		lead: 'Add radionuclides to the model from the 1,252 of ICRP Publication 107, with their '
			+ 'half-lives and the decay chains that join them.',
		sections: [{
			text: [
				'Elements down the left and their isotopes beside them; the search takes a name, a symbol, or '
				+ 'an element in words.',
				'Tick a nuclide and the band underneath says what the model would contain, and which '
				+ 'short-lived members of its chain it passes through rather than modelling.',
			],
		}],
		more: 'Choosing nuclides from ICRP 107',
	},
	shape: {
		title: 'Shape',
		lead: 'A shape drawn on the canvas behind the model, and how it looks: its figure, fill, line, '
			+ 'text, size and alignment.',
		sections: [{
			text: 'Every change applies at once \u2014 the shape is behind the dialog, and the point of '
				+ 'changing its colour is to see it. Shapes are drawing, not model: they change no number.',
		}],
		more: 'Shapes on the canvas',
	},
	'shape-picker': {
		title: 'Add a shape',
		lead: 'A figure to draw on the canvas behind the blocks — ground, water, a tree, a building, an '
			+ 'arrow, a note — so that the diagram reads as the place it models.',
		sections: [{
			list: [
				'Every figure is shown as the canvas will draw it, in six groups: basic, arrows, landscape, '
				+ 'living, built and notes. The search box takes a name or a group.',
				'Click one to add it where the menu was opened. Double-click it on the canvas afterwards for '
				+ 'its settings: fill, line, text, size.',
			],
		}, {
			text: 'Shapes are drawing, not model: they are saved with the model, and nothing in it reads them.',
		}],
		more: 'Shapes on the canvas',
	},
	'data-import': {
		title: 'Import data',
		lead: 'Values from a spreadsheet or an HDF5 file, read onto this model’s parameters and lookup '
			+ 'tables by their IDs.',
		sections: [{
			text: 'It says what it would change before it changes anything, and what it could not place.',
		}],
		more: 'Handing the data over',
	},
	'import-blocks': {
		title: 'Import blocks',
		lead: 'Blocks from another model file, brought into this one: what the file holds on the left, and '
			+ 'on the right what taking it would mean — worked out before anything is taken.',
		sections: [{
			heading: 'On the left',
			text: 'Tick blocks, or a whole sub-system at once; shift-click ticks a run of them. The search takes '
				+ 'a name or a pattern such as `*_out`. A row marked as coming anyway is one that what you '
				+ 'ticked reads, or one that joins two blocks that are coming.',
		}, {
			heading: 'On the right',
			list: [
				'**Coming across** — how many blocks, and with **Bring what they need** on, the parameters, '
					+ 'expressions and compartments their equations refer to. A transfer comes only with the '
					+ 'blocks at both its ends.',
				'**Index lists** — each dimension the blocks have that this model lacks or holds differently: '
					+ 'add it, use one of this model’s instead, or drop it. Choices, not warnings.',
				'**Radionuclides** — the nuclides that would be added. Where the two models disagree on a '
					+ 'half-life, this model keeps its own.',
				'**Names already used** — a name taken where a block lands gets a number, as a paste does.',
				'**Afterwards** — whether the model will still build, found by making the import on a copy.',
			],
		}, {
			text: '**Into** says where the blocks land: wherever they were in the file, the top level, or a '
				+ 'sub-system. Nothing is written to this model until **Import** is pressed; **Another file…** '
				+ 'reads a different one.',
		}],
		more: 'Importing blocks from another model',
	},
	'import-chooser': {
		title: 'What to do with this file',
		lead: 'What the file holds, read first, and what can be done with each part of it.',
		sections: [{
			text: 'The extension does not say whether a file is a model, a run or a table of values, so it '
				+ 'is read before anything is asked.',
		}],
		more: 'Importing blocks from another model',
	},
	'version-report': {
		title: 'Version report',
		lead: 'Every block, list, nuclide and setting that differs between this model and another version '
			+ 'of it.',
		sections: [{ text: 'The layout on the canvas is left out; comments are counted.' }],
		more: 'Version report',
	},
	'run-log': {
		title: 'Run log',
		lead: 'What the run was, in words that survive it: the settings, the solver’s account of the '
			+ 'run, what was held at zero, and the probabilistic run if one stands.',
		sections: [{ text: 'Kept with a saved result, so an archive says what it is without this page.' }],
		more: 'The run log',
	},
};

/**
 * The `info` option for `openModal`: `{key, topic}`.
 *
 * @param {string} id  a key of the table above
 * @returns {{key: string, topic: () => object}|null}
 */
export function dialogInfo(id) {
	const t = TOPICS[id];
	if (!t) return null;
	return { key: `dialog:${id}`, topic: () => ({ kicker: KICKER, ...t }) };
}

/** Every dialog with a topic, for the tests. */
export const DIALOG_TOPICS = Object.keys(TOPICS);
