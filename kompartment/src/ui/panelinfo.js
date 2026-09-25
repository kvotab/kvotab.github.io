/**
 * What each part of the left panel holds, for the information panel
 * (./infopanel.js): the Model and Simulation sections, the tree with its
 * search and filters, and the Information view.
 *
 * The rows of the Simulation section have topics of their own (./siminfo.js);
 * these are one level up -- what a section is for and what is in it, for
 * somebody who has not opened it yet.
 */

const KICKER = 'Left panel';

/**
 * @param {'model'|'simulation'|'tree'|'information'} key
 * @param {object} [ctx]
 * @param {boolean} [ctx.systems]  the model has sub-systems
 * @param {boolean} [ctx.sample]   a probabilistic run stands
 * @returns {object|null}
 */
export function panelTopic(key, ctx = {}) {
	switch (key) {
		case 'model': return {
			kicker: KICKER,
			title: 'Model',
			lead: 'What the model is called and what it is: the two things the window’s header shows, '
				+ 'and the file is saved under.',
			sections: [{
				heading: 'What is here',
				list: [
					'**Name** — shown in the header and used for the file name when the model is saved. '
					+ 'Changing it changes no number, so nothing is run again.',
					'**Description** — what the model is and where it came from, in plain text. The '
					+ 'Information view shows it when nothing is selected, and a results file carries it.',
					'**Track review** — record which definitions have been reviewed and approved, and '
					+ 'notice when an approval lapses because the block, or something it is worked out from, '
					+ 'has changed since. The tally under it lists the blocks a review has not signed off.',
					'**Compare with** — a version report: every block, list, nuclide and setting that '
					+ 'differs between this model and the one it was opened as, or another file.',
				],
			}, {
				text: 'The section starts folded: it is read once and changed rarely, and the room goes '
					+ 'to the tree below.',
			}],
			more: 'Recording that a definition has been reviewed',
		};
		case 'simulation': return {
			kicker: KICKER,
			title: 'Simulation',
			lead: 'How the model is run: over what span, reported at which times, by which solver and to '
				+ 'what tolerance — and the analyses that run it many times.',
			sections: [{
				heading: 'What is here',
				list: [
					'**Scenario** and **Run**, when the model has a scenario list: which future it is built '
					+ 'at, and which others run beside it.',
					'**Start**, **End**, **Output points**, **Time spacing** and **Time unit** — the span '
					+ 'and the times the results are reported at.',
					'**Solver**, **Rel. tolerance** and **Abs. tolerance** — what integrates the model '
					+ 'and how accurately.',
					'**dy/dp**, **Calibration** and **Uncertainty** — a sensitivity integrated with the '
					+ 'model, solving for inputs, and the probabilistic run with what can be asked of it.',
					'**Advanced settings**, folded — first **Cannot go negative enabled**, **Mass balance** '
					+ 'and **Split into parts**, three switches on how any solver behaves; then what the '
					+ 'chosen solver reads beyond the tolerances, where an empty box shows, greyed, what the '
					+ 'solver will use.',
				],
			}, {
				text: 'Every row has its own (i), on the right, saying what it does and what an empty box '
					+ 'comes to. The badge beside the heading says the span and the solver while the section '
					+ 'is folded.',
			}],
			more: 'The solver’s own settings',
		};
		case 'tree': return {
			kicker: KICKER,
			title: 'The tree of the model',
			lead: 'Every block in the model, under the sub-systems it lives in, with the search and the '
				+ 'filters above it and the buttons that add blocks on its top edge.',
			sections: [{
				heading: 'Finding a block',
				list: [
					'**The search box** matches anywhere in a block’s name. With `*` or `?` it is a '
					+ 'pattern over the whole name: `*` any run of characters, `?` exactly one — `C*_out`. '
					+ 'Escape clears it.',
					'**Group by type** files the blocks of each sub-system under a heading per kind, which is '
					+ 'worth having when one sub-system holds hundreds of them.',
					'**?** asks the model a question — what reads this block, what it needs, what nothing '
					+ 'reads, which blocks are only data — and pins the answer over the tree until its × '
					+ 'is pressed.',
					...(ctx.sample ? ['**Probabilistic** shows only the blocks the probabilistic run has '
						+ 'realisations of: the endpoints it kept and the parameters it varied.'] : []),
					'**All kinds** opens the kind filter: a chip per kind of block, as many as you like. None '
					+ 'ticked means every kind. While anything filters, the line says how many of the blocks '
					+ 'are shown, and **Clear** puts it all back.',
				],
			}, {
				heading: 'Adding and arranging',
				list: [
					'**Add** — a compartment, an expression or a parameter, made in the sub-system the '
					+ 'diagram is showing and selected, so its settings are a double-click away.',
					...(ctx.systems ? ['**Expand all** and **Collapse** open or close every sub-system at '
						+ 'once.'] : []),
					'Drag rows onto a sub-system to move them into it.',
				],
			}, {
				heading: 'The rows',
				list: [
					'Click a block to select it, here and on the diagram; double-click to open its settings. '
					+ 'Click a sub-system to show it on the diagram; its arrow opens it without going there.',
					'Right-click a row for the block\u2019s menu: its settings, cut, copy and paste, moving '
					+ 'it to another sub-system, and delete.',
					'The keyboard walks it as a tree is walked: up and down, right to open or step in, left to '
					+ 'close or step out, Enter to select, Delete to delete, `*` to open every sibling.',
					'A block carries the icon of the shape the diagram draws it with; beside it, the value, '
					+ 'the equation or the dimensions it has. A sub-system says how many blocks it holds, and a '
					+ 'mark says when something in it needs looking at.',
				],
			}, {
				text: 'The line between the tree and the Information view divides the height between them: '
					+ 'drag it, or double-click it to even them up.',
			}],
			more: 'Asking the model about itself',
		};
		case 'information': return {
			kicker: KICKER,
			title: 'Information',
			lead: 'What the selected block is, and what it is joined to — for reading, not editing. With '
				+ 'nothing selected, the model; inside a sub-system, that sub-system.',
			sections: [{
				heading: 'What it shows',
				list: [
					'The block’s kind, unit, dimensions and the equation or value that defines it, with '
					+ 'its values per index when it has several and what it comes to at the start.',
					'The blocks its equation reads, and the blocks that read it. Each is a link: click it to '
					+ 'go there.',
					'Anything wrong with it that the model’s scan has found, such as a unit that does not '
					+ 'work out.',
				],
			}, {
				heading: 'Its title bar',
				list: [
					'**⧉**, beside the name, takes the view out into a window of its own, which can be '
					+ 'moved by its title bar and sized by its corner. The tree has the whole panel while '
					+ 'it is out; closing the window puts the view back. The window is remembered in this '
					+ 'browser.',
					'**Edit…** opens the block’s settings — as double-clicking it does, on the diagram, '
					+ 'in the tree, or on its name here.',
					'**Open** shows a sub-system on the diagram, and **Up** the one around it.',
					'**←** and **→** go back and forward through the blocks you have followed links to, '
					+ 'as a browser does through pages.',
				],
			}, {
				text: 'Right-click the name for the block’s menu. Folded, the view gives its share of the '
					+ 'height back to the tree.',
			}],
			more: 'What it does',
		};
		default:
			return null;
	}
}
