/**
 * What the App designer's parts are, for the information panel
 * (./infopanel.js): the tab itself, each kind of component, what an input can
 * be pointed at, what a result can show, and the app's own settings.
 *
 * Plain data, like the other topic files. Every topic ends on the heading of
 * the Guide section that says the rest, and a test holds each of those to a
 * heading that exists.
 */

import { COMPONENTS, STATISTICS, CURVES, THEMES } from '../domain/apps.js';

const KICKER = 'App designer';

/** What each kind of component is for, and what it is set by. */
const PARTS = {
	slider: {
		lead: 'Sets a number by dragging along a range: a parameter’s value, a compartment’s value at '
			+ 'the start, a factor on every index of one, or the end of the run.',
		list: [
			'**Min** and **Max** — the ends of the range. A new slider takes them from the parameter’s '
			+ 'distribution where it has one, and a decade either side of its value where not.',
			'**Scale** — **log** spreads the range evenly in the logarithm, which is how a rate spanning '
			+ 'decades is best dragged; it needs a range above zero.',
			'**Step** — for a linear slider, the steps it moves in: whole years, say. Empty is smooth.',
			'The box beside the name takes a number typed in, inside the range or outside it.',
		],
	},
	number: {
		lead: 'Sets a number typed into a box: the same things a slider sets, for a value that is better typed '
			+ 'than dragged.',
		list: ['**Min** and **Max** are optional; a number outside them is brought to the nearer end.'],
	},
	dropdown: {
		lead: 'Chooses one of a list: the model’s scenario, or a parameter’s value from choices you name.',
		list: [
			'Pointed at **Scenario**, it offers the model’s scenarios and needs nothing more.',
			'Pointed at a value, it offers the **choices** listed under it: each a label and the number it sets.',
		],
	},
	radio: {
		lead: 'The same choice as a drop-down, with every choice on show as a button of its own — for two to '
			+ 'five of them.',
		list: ['Set up exactly as a drop-down is.'],
	},
	switch: {
		lead: 'On or off: whether a block takes part in the run, or a parameter at one of two values.',
		list: [
			'Pointed at a **block**, off leaves it out of the run, as **Disable** does in the editor.',
			'Pointed at a value, **On** and **Off** are the two numbers it sets — 1 and 0 unless you say.',
		],
	},
	button: {
		lead: 'Runs the model at the values the controls hold, samples the spread of the results there, or puts '
			+ 'every control back to the value the model holds.',
		list: [
			'An app set to run only when asked needs a **Run** button, and the app’s title bar has one.',
			'**Run the spread** runs the model many times at the controls, drawing every input that carries a '
				+ 'distribution; the results that read the spread show it.',
		],
	},
	chart: {
		lead: 'The series you name, over time, as the Chart tab draws them: drag to zoom, double-click for '
			+ 'everything.',
		list: [
			'**Series** — a block, and at which indices; an index left at *every one* draws a line for each.',
			'**X axis** and **Y axis** — logarithmic or linear. A chart of up to 32 lines.',
			'**Spread** — the percentile bands of a sampled run behind each line, 5–95 and 25–75; and **the mean** '
				+ 'of the realisations as a line of its own.',
		],
	},
	value: {
		lead: 'One number read off one series — its peak, its value at the end or at a time you give — large, '
			+ 'with its unit.',
		list: [
			'**Limit** — optional. The number turns red above it and green below it, and says which.',
			'**Digits** — the significant figures it is shown to.',
			'**Of** — the run at the controls, or the mean, the median or a percentile of a sampled run: the '
				+ 'peak of the 95th percentile, say.',
		],
	},
	gauge: {
		lead: 'One number read off one series, as a needle on a dial between two ends.',
		list: [
			'**Min** and **Max** — the ends. Left empty, the dial runs from nought to a round number above the '
			+ 'value and the limit.',
			'**Limit** — optional: a mark on the dial, and the arc turns red past it.',
		],
	},
	bars: {
		lead: 'One number from each of several series, side by side as bars: the peak dose of every '
			+ 'radionuclide, say.',
		list: [
			'**Series** — as a chart’s: an index left at *every one* is a bar for each.',
			'**Scale** — logarithmic by default, over the six decades below the largest bar.',
			'**Largest first** — sorts the bars by their value.',
		],
	},
	table: {
		lead: 'The series you name, at a column each, over a list of times.',
		list: [
			'**Times** — the times the rows are at, separated by commas; a time between two output times is '
			+ 'read off the straight line between them.',
			'**Rows** — with no times given, this many of the run’s own output times, evenly along its list.',
		],
	},
	panel: {
		lead: 'A titled box with a grid of its own: the inputs of one kind together, a result and its notes. '
			+ 'Twelve columns across the panel, and it grows to hold what is put in it.',
		list: [
			'Drag parts into it, or select it and click one in the list: it goes into the panel.',
			'**Take it out** puts a part back onto the page; a part is moved from one panel to another by dragging.',
			'Panels and tabs go three deep: a panel in a tab of a set of tabs in a panel.',
		],
	},
	tabs: {
		lead: 'Several grids in the space of one, a tab each, one showing at a time: the inputs on one tab and '
			+ 'the detail on another, beside a chart that stays.',
		list: [
			'Choose a tab on the page to put parts on it; **+** adds one, and right-clicking a tab renames, moves or '
				+ 'deletes it.',
			'Somebody using the app chooses the tab; which one is showing is theirs, and is not saved.',
		],
	},
	image: {
		lead: 'A picture on the page: a sketch of the system, a map of the site, a logo.',
		list: [
			'**Choose a picture…**, or drop a picture file onto the page. PNG, JPEG, GIF, WebP or SVG.',
			'The picture is kept in the model file, so it goes wherever the file goes; a large one is made smaller '
				+ 'first, to at most 1600 pixels on its longer side.',
			'**Describes** is what a screen reader says for it; **Fits** shows it whole or fills the box with it.',
		],
	},
	text: {
		lead: 'Words on the page: a title, a heading, a note, or a paragraph that says what the app is for.',
		list: [
			'Written as Markdown — `**bold**`, `*italic*`, lists starting `- `, and web addresses as links.',
			'**Style** — body, title, heading or note; **Align** — left, centre or right.',
		],
	},
};

/**
 * @param {string} key  `designer`, `part:<type>`, `target`, `series`,
 *   `statistic`, `app` or `page`
 * @returns {object|null}
 */
export function appTopic(key) {
	if (key.startsWith('part:')) {
		const type = key.slice(5);
		const part = PARTS[type];
		const spec = COMPONENTS[type];
		if (!part || !spec) return null;
		const kind = { input: 'input', output: 'result', layout: 'layout' }[spec.group] ?? 'text and pictures';
		return {
			kicker: `${KICKER} · ${kind}`,
			title: spec.name,
			lead: part.lead,
			sections: [{ heading: 'Its settings', list: part.list }, {
				text: '**Where it is** — drag it by its body to move it, and by its bottom-right corner to resize '
					+ 'it; the arrow keys move it a cell at a time and shift with an arrow resizes it. What it '
					+ 'lands on moves down out of the way.',
			}],
			more: { panel: 'Panels and tabs', tabs: 'Panels and tabs', image: 'Pictures' }[type] ?? 'The parts of an app',
		};
	}
	switch (key) {
		case 'designer': return {
			kicker: 'Tab',
			title: 'App designer',
			lead: 'An app is a page of controls and results over this model, for somebody who does not need '
				+ 'the editor: a few sliders, a chart, a number or two. **Run app** shows it and nothing else, and '
				+ 'each change to a control runs the model at the values the controls hold.',
			sections: [{
				heading: 'Building one',
				list: [
					'**Drag** a part from the list on the left onto the page, or click it to add it where there is room.',
					'**Drag a parameter from the tree** onto the page for a slider over it, and a compartment or an '
					+ 'expression for a chart of it.',
					'**Select** a part to set it up on the right: what it sets or shows, its range, its title.',
					'**Start from the model** makes a first app: sliders for the parameters that carry a '
					+ 'distribution, a chart of the endpoints, and their peak.',
					'**Panels** and **tabs** hold parts of their own; a **picture** is dropped on the page as a file.',
					'**Share…** makes a link that opens the model as its app, in anybody’s browser.',
				],
			}, {
				heading: 'What it changes',
				text: 'Nothing the model computes. The app is saved in the model file, and follows a rename of '
					+ 'anything it points at; moving a control runs a copy of the model at the control’s value, '
					+ 'and the model keeps its own. Laying out the page is an edit like any other, so Undo takes it back.',
			}],
			more: 'Apps on a model',
		};
		case 'target': return {
			kicker: KICKER,
			title: 'What an input sets',
			lead: 'An input is pointed at one thing in the model, and a run of the app is made on a copy of '
				+ 'the model with that thing at the input’s value.',
			sections: [{
				choices: [
					['A parameter', 'its value; for a parameter with an index list, the value at one index.'],
					['A compartment', 'its value at the start, the same way.'],
					['Every index', 'a factor on what the model holds at each index left at *every one* — '
						+ '`Kd ×` doubles every nuclide’s Kd at 2.'],
					['Scenario', 'which scenario is live, for a drop-down or option buttons.'],
					['End of the run', 'the end time, for a slider or a number field.'],
					['A block on or off', 'whether the block takes part, for a switch.'],
				],
			}, {
				text: 'Two inputs pointed at the same thing share one value, so a slider and a number field over '
					+ 'one parameter move together.',
			}],
			more: 'What an input sets',
		};
		case 'series': return {
			kicker: KICKER,
			title: 'What a result shows',
			lead: 'A result names blocks of the model, and at which of their indices: the series a run '
				+ 'reports for them are what it draws.',
			sections: [{
				list: [
					'An index left at **every one** takes each index of that list: `Dose` over the radionuclides '
					+ 'is a line, or a bar, per radionuclide.',
					'A value and a gauge show one number, so they take one index of each list.',
					'Anything a run reports can be shown — a compartment, an expression, a flux, a parameter, a '
					+ 'recorder — by the name it has in the tree.',
				],
			}],
			more: 'What a result shows',
		};
		case 'statistic': return {
			kicker: KICKER,
			title: 'The number read off a series',
			lead: 'A value, a gauge and a bar chart each show one number per series, read off the whole run.',
			sections: [{
				choices: Object.entries(STATISTICS).map(([k, name]) => [name, {
					final: 'the value at the last output time.',
					max: 'the largest value the series reaches, and when.',
					max_time: 'the time at which the series is largest, in the model’s time unit.',
					min: 'the smallest value it reaches.',
					initial: 'the value at the first output time.',
					at: 'the value at a time you give, read off the straight line between the output times either side.',
					mean: 'the average over the span of the run, weighting each stretch by how long it lasts.',
				}[k]]),
			}],
			more: 'What a result shows',
		};
		case 'app': return {
			kicker: KICKER,
			title: 'The app',
			lead: 'Its title and description head the running app; the rest is how it runs and how it opens.',
			sections: [{
				choices: [
					['Looks', 'one of the styles an app can wear when it runs — Swiss, Newsprint, Terminal and the rest; '
						+ 'the page shows it as it is designed. See **How an app looks**.'],
					['Runs the model', '**whenever a control changes** — a slider runs as it is let go, and while '
						+ 'it is dragged too when the model solves quickly — or **when Run is pressed**, for a model '
						+ 'that takes long enough that one run at a time is enough.'],
					['Opening the file shows', '**the app** opens a file that carries it straight into the app, '
						+ 'which is what somebody the file is sent to wants; **the editor** opens it as usual.'],
					['Offer Edit while it runs', 'the way back to the editor, at the right of the title bar. '
						+ 'Leaving it off hides it from somebody who opened the app straight from a file; the '
						+ 'designer’s own Run app always has it, and Esc. Its author still has ⌘⇧E, and '
						+ '`?app=off` in the address.'],
				],
			}],
			more: 'Running an app',
		};
		case 'spread': return {
			kicker: KICKER,
			title: 'The spread of the results',
			lead: 'A sampled run of the app: the model run many times at the controls, each time with every input '
				+ 'that carries a distribution drawn afresh — except what a control has been moved to.',
			sections: [{
				list: [
					'A control moved away from the model’s value **holds** its input there: whoever moved the slider '
						+ 'has said what it is. One still at the model’s value leaves the input to its distribution.',
					'A control that sets a **factor** on every index scales the input’s distribution: `Kd ×` at 2 '
						+ 'samples twice each nuclide’s Kd.',
					'**Realisations** — how many runs, 200 unless you say. **Sampled** — when **Run the spread** is '
						+ 'pressed, or after every change of a control.',
					'A chart draws its **bands** from it, and a value, a gauge, a bar chart or a table reads its '
						+ '**mean**, its **median** or a percentile:',
				],
				choices: Object.entries(CURVES).filter(([k]) => k !== 'run'),
			}, {
				text: 'A sample is of the controls as they stood when it ran: move one and its bands go, until it is '
					+ 'run again.',
			}],
			more: 'The spread of the results',
		};
		case 'theme': return {
			kicker: KICKER,
			title: 'How an app looks',
			lead: 'The style the app wears — its colours, its type, its lines and shadows — named after the design '
				+ 'style it follows. The page in the designer wears it too, so it is seen as it is laid out.',
			sections: [{
				list: THEMES.map((t) => `**${t.name}**${t.mode === 'dark' ? ', dark' : t.mode === 'light' ? ', light' : ' — this tool’s own, light or dark with the page'}`),
			}, {
				text: 'Each has eight chart colours of its own, chosen for its background and checked against it: '
					+ 'lines next to each other in a chart are told apart with colour-blindness as well as without. '
					+ 'The fonts are the ones the computer has; nothing is fetched for a style.',
			}],
			more: 'How an app looks',
		};
		case 'page': return {
			kicker: KICKER,
			title: 'Pages',
			lead: 'An app can be several pages, shown as tabs across the top of the running app: the inputs and '
				+ 'the main result on one, the detail on another.',
			sections: [{
				list: [
					'**+** adds a page; right-click a page’s tab to rename, move or delete it.',
					'A part is moved to another page from its settings.',
					'Every page reads the same run: moving a slider on one updates the results on all of them.',
				],
			}],
			more: 'Designing an app',
		};
		default: return null;
	}
}

/** Every key a topic answers to, for the test that checks them. */
export const APP_TOPICS = ['designer', 'target', 'series', 'statistic', 'app', 'page', 'spread', 'theme',
	...Object.keys(COMPONENTS).map((t) => `part:${t}`)];
