/**
 * What each kind of block is, and what its settings window holds, for the (i)
 * in the window's title bar (./infopanel.js).
 *
 * One topic per kind, written for somebody who has just double-clicked a block
 * and is looking at its window: what the block does in the model, what each of
 * its own settings is for, and the part every block's window has in common.
 * The Guide section that says the rest is linked at the foot.
 */

/** What every block's window has, whatever its kind. */
const COMMON = [
	'**Name** — what equations call it; renaming it renames every reference. A block may also '
	+ 'have a display name for the diagram, with sub- and superscripts.',
	'**Sub-system** — where it lives.',
	'**Unit** — what its value is measured in. Checked against the units of whatever it reads, '
	+ 'and said in the problems strip when they do not work out.',
	'**Indexed by** — the index lists it has a value per combination of, such as the '
	+ 'radionuclides. What the lists hold is edited on the Index lists tab.',
	'**Values per index** — a value of its own for particular indices, where the one above is '
	+ 'only the default.',
	'**Appearance** — its colour and shape on the diagram. **Comment** — notes that travel '
	+ 'with the model. **Review** — approvals, when the model tracks them.',
	'**Enabled** — switched off, a block stays in the model and takes no part in the run.',
];

/** A topic from a kind's own parts. */
const topic = (title, lead, own, { diagram, file, more, note } = {}) => ({
	kicker: 'Settings window',
	title,
	lead,
	facts: [['On the diagram', diagram], ['In the model file', file]],
	sections: [
		{ heading: 'Its own settings', list: own },
		...(note ? [{ text: note }] : []),
		{ heading: 'Every block has', list: COMMON },
	],
	more,
});

/** The topic for a block of `kind`, or null for a kind with none. */
export function blockTopic(kind) {
	switch (kind) {
		case 'compartment': return topic('Compartment',
			'An inventory the solver integrates: what is in it changes by what the transfers and '
			+ 'inflows move in and out, and by decay and ingrowth.',
			[
				'**Initial inventory** — what it holds at the start, per index. An equation may read '
				+ 'parameters and other blocks’ starting values.',
				'**Handle decay and ingrowth** — whether the radionuclides in it decay, and their '
				+ 'daughters grow in, along the model’s decay chains.',
				'**Cannot go negative** — hold it at zero where the equations would push it below. '
				+ 'The status line counts every compartment it had to hold.',
				'**Absolute tolerance** — its own, for amounts on another scale from the rest of the '
				+ 'model. Empty is the model’s.',
				'**Availability** — when only part of the inventory can move: a limit such as a '
				+ 'solubility, shared over the isotopes of an element and summed in moles or in the '
				+ 'inventory’s own unit, with what is held back kept or carried on.',
			],
			{ diagram: 'a rounded box', file: '`compartments`', more: 'When only part of an inventory can move' });
		case 'transfer': return topic('Transfer',
			'A flow from one compartment to another, or out of the model: the arrow between two boxes.',
			[
				'**From** and **To** — its two ends; either may be outside the model.',
				'**The rate is** — a rate coefficient, a fraction per unit time multiplied by what is '
				+ 'in the source, or a flux, an amount per unit time as it stands.',
				'**Rate coefficient** or **Flux** — the equation, per index. Its unit is worked out '
				+ 'from its ends and said beside it.',
			],
			{
				diagram: 'an arrow from one box to another',
				file: '`transfers`',
				more: 'A transfer does not choose its dimensions',
				note: 'A transfer does not choose its dimensions: it is indexed by what its two ends have in '
					+ 'common, which the window says. A release out of a waste package or a far-field path '
					+ 'is worked out by that block and has no equation to set here.',
			});
		case 'inflow': return topic('Inflow',
			'A source term: an amount per unit time added straight into a compartment from outside the '
			+ 'model.',
			[
				'**Into** — the compartment it feeds.',
				'**Input rate** — the amount per unit time, per index; an equation may read the clock '
				+ 'and any block.',
				'**Sum extra indices** — when the rate has dimensions its compartment has not, add them '
				+ 'up rather than refusing.',
			],
			{ diagram: 'an arrow in from outside: a cloud at its start, or the radiation sign for radionuclides', file: '`inflows`', more: 'Your first model' });
		case 'parameter': return topic('Parameter',
			'A number, or an equation of numbers: an input the model reads. The one kind that can carry a '
			+ 'distribution for a probabilistic run.',
			[
				'**Value** — the number, per index where it is indexed; the default applies wherever no '
				+ 'index has a value of its own.',
				'**Distribution** — what a probabilistic run draws it from: uniform, triangular, normal, '
				+ 'their log forms, a list of values; truncated if you like, and correlated with others. '
				+ 'Click it to choose one. A run here is deterministic and uses the value; the '
				+ 'distribution is what a probabilistic run samples.',
			],
			{ diagram: 'a hexagon', file: '`parameters`', more: 'A distribution on a parameter' });
		case 'expression': return topic('Expression',
			'A quantity worked out from other blocks at every step — a concentration, a dose, a rate.',
			[
				'**Equation** — how it is worked out, per index where it is indexed. Completion offers '
				+ 'the blocks it can name and the function library as you type.',
				'Its unit is worked out from the equation’s and said beside it.',
			],
			{
				diagram: 'a dashed rounded box marked =',
				file: '`expressions`',
				more: 'Pinning an index in an equation',
				note: 'A part of a transport chain shows the chain’s own settings — what it works out, '
					+ 'over what, and how many compartments — instead of an equation.',
			});
		case 'lookup': return topic('Lookup table',
			'A value read off a table: of time, or of an argument it is called with.',
			[
				'**Points** — the table itself, per index where it is indexed.',
				'**Read at** — the clock, or an argument: `Q_gw(x)` reads the table at `x`.',
				'**Interpolation** — how it goes between points: a straight line, or a step.',
				'**Repeat the table** — read it again from the start when the argument runs past its end.',
			],
			{ diagram: 'a box marked with a curve', file: '`lookups`', more: 'Lookup tables' });
		case 'index_reduction': return topic('Reduce over an index',
			'One block’s values collapsed along one of its index lists: the sum over the nuclides, the '
			+ 'largest over the regions.',
			[
				'**Reduce** — the block to reduce.',
				'**Reduced over** — the list it is collapsed along; the result keeps the others.',
				'**Reduce by** — sum, mean, largest, smallest, a percentile, and the rest; '
				+ '**Percentile** says which.',
			],
			{ diagram: 'a rounded box marked with a funnel', file: '`index_reductions`', more: 'Reducing a dimension' });
		case 'block_reduction': return topic('Combine blocks',
			'Several blocks combined into one value: the total over a set of compartments, the largest of '
			+ 'several doses.',
			[
				'**Blocks** — which to combine, per index where it is indexed.',
				'**Reduce by** — how: the sum, the mean, the largest, the smallest.',
			],
			{ diagram: 'a rounded box marked +', file: '`block_reductions`', more: 'Reducing a dimension' });
		case 'function': return topic('Function',
			'An equation of its own arguments, called by name from any other equation: `Dose(c, f)`.',
			[
				'**Parameters** — the names of its arguments.',
				'**Body** — the equation, in terms of them. It may read other blocks too.',
			],
			{ diagram: 'not drawn: it is called by name, not connected', file: '`functions`', more: 'Functions' });
		case 'min_max': return topic('Min/max',
			'The largest or smallest value something has reached so far in the run — the peak dose.',
			[
				'**Watching** — what it records the extreme of.',
				'**Keep the** — the largest value, or the smallest.',
				'**Reset at**, **Start at**, **Stop at** — discrete events that start the extreme again, '
				+ 'start recording, and stop it. Left at never, it records the whole run.',
			],
			{ diagram: 'a box marked with a peak', file: '`min_maxes`', more: 'Blocks that remember' });
		case 'running_mean': return topic('Running mean',
			'The average of something over the run so far, integrated as the solver goes.',
			[
				'**Watching** — what it averages.',
				'**Reset at**, **Start at**, **Stop at** — discrete events that start the mean again, '
				+ 'start it, and stop it.',
			],
			{ diagram: 'a box marked with a mean', file: '`running_means`', more: 'Blocks that remember' });
		case 'snapshot': return topic('Snapshot',
			'What something was at the moment an event fired, held from then on.',
			[
				'**Watching** — what it takes the value of.',
				'**Taken at** — the discrete event that takes it.',
				'**Before then** — what it reads until the event first fires.',
			],
			{ diagram: 'a box marked with a sample', file: '`snapshots`', more: 'Blocks that remember' });
		case 'delay': return topic('Delay',
			'Something as it was a fixed time ago.',
			[
				'**Watching** — what it delays.',
				'**Delayed by** — how long ago, in the model’s time unit.',
			],
			{ diagram: 'a cylinder', file: '`delays`', more: 'Blocks that remember' });
		case 'trigger': return topic('Trigger',
			'A discrete event: the instant one equation crosses another. The solver stops there and starts '
			+ 'again from it, so what the event drives happens when it happens.',
			[
				'**First** and **Second** — the two equations; it fires where their difference changes '
				+ 'sign.',
				'**Fires** — rising, falling, or either way.',
				'Snapshots, and the min/max and running means, name it in their **Taken at** and '
				+ '**Reset at** to act when it fires.',
			],
			{ diagram: 'a diamond marked with a step', file: '`triggers`', more: 'Blocks that remember' });
		case 'event': return topic('Event',
			'Something that happens to the model at an instant: packages breached, a share of an inventory '
			+ 'moved — an earthquake, a glaciation, a well drilled.',
			[
				'**Happens** — once, at a time; or at random at a rate, between two times.',
				'**At**, **Rate**, **From**, **Until** — when, as the choice above asks.',
				'**Does** — its actions: fail a share of the packages in a waste-package block, or move a '
				+ 'share of a compartment’s inventory to another compartment or out of the model.',
				'**Draw the occurrences in a probabilistic run** — each realisation draws its own times; '
				+ 'a deterministic run takes the expected-value form.',
			],
			{ diagram: 'a diamond marked with a bolt', file: '`events`', more: 'Events' });
		case 'waste_package': return topic('Waste packages',
			'The source term with its barriers: an inventory inside intact packages, released as they fail '
			+ 'and as the waste form degrades.',
			[
				'**Release** — the compartment or far-field path what is released goes to.',
				'**Packages** — how many there are.',
				'**Packages fail** — how: all at a time, or over time by a failure law.',
				'**Matrix degradation rate** — how fast the exposed waste form dissolves. The inventory, the '
				+ 'instant-release fraction and the rate can each differ per index, under **Values per index**: '
				+ 'per nuclide, or per waste type when the block is indexed by one.',
				'**Handle decay and ingrowth** — whether the inventories decay inside the packages.',
			],
			{ diagram: 'a box marked with a canister', file: '`waste_packages`', more: 'Waste packages: the source term with its barriers' });
		case 'farfield': return topic('Far-field pathway',
			'A transport path through fractured rock (FARFCOMP): advection along fractures, diffusion into '
			+ 'the rock matrix beside them, sorption and decay — worked out on cells with the rest of the '
			+ 'model, or semi-analytically from the path’s transfer function.',
			[
				'**Worked out** — *on cells*: the fracture and the rock divided into cells, solved with '
				+ 'the rest of the model, every setting free to change during the run. *Semi-analytically*: '
				+ 'the path solved exactly once per run, and what flows in convolved with its responses — '
				+ 'one state per nuclide for what it holds, no cells to refine, the settings constant '
				+ 'through the run and the rock going on past the release point.',
				'**Release** — the compartment what leaves the far end goes to.',
				'**Flow-wetted surface given as** — F, the flow-related transport resistance; a_w, the '
				+ 'wetted surface per volume of flowing water; or δ, the fracture aperture (a_w = 2/δ). '
				+ 'The other two are worked out under the choice, and switching keeps the path the same.',
				'The path’s own settings — the water travel time, the Peclet number, the rock’s density, '
				+ 'the matrix depth — one value each.',
				'The chemistry — sorption, diffusivity, porosity — per nuclide, under **Values per '
				+ 'index**. A stable species does not decay, and a list of chemical species decays along '
				+ 'nothing: a path needs no radionuclides.',
				'**Discretisation**, on cells — how many cells along the path and into the matrix, and '
				+ 'how the matrix layers are laid out: matched to diffusion into the rock, from a first '
				+ 'layer worked out from the path’s own time scales, or as in SKB’s reference '
				+ 'implementation. Worked out semi-analytically only the depth into the matrix is left, '
				+ 'beside the chemistry.',
				'**Water downstream of the path** — new paths have the rock going on past the release '
				+ 'point, as in FARF31, with a few cells of it beyond: **Cells past the release point**, '
				+ 'empty to have them worked out.',
				'**Report every cell** — chart each cell, not only what the path releases.',
				'**Handle decay and ingrowth** — whether the nuclides decay on the way.',
			],
			{ diagram: 'a box marked with a fracture', file: '`farfields`', more: 'Far-field pathways (FARFCOMP)' });
		default:
			return null;
	}
}
