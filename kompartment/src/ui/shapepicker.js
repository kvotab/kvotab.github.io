/**
 * Choosing a shape to draw on the canvas.
 *
 * A menu would have done -- six submenus of names -- but a name is not what
 * you pick a shape by. `mire`, `bedrock` and `soil` are three words for
 * three drawings, and the drawings tell them apart in a glance where the words
 * do not. So the dictionary is shown as itself: every figure at thumbnail
 * size, grouped, with a search box for the ones who already know what they
 * want.
 *
 * Nothing here touches the model. It calls back with a figure name and closes;
 * the canvas is what adds the shape, where the menu was opened.
 */

import { openModal, closeModal } from './modal.js';
import {
	FIGURES, FIGURE_GROUPS, ROLES, figureParts, figureSize,
} from './figures.js';
import { el } from './parts.js';

const NS = 'http://www.w3.org/2000/svg';

const svg = (name, attrs = {}) => {
	const n = document.createElementNS(NS, name);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

/**
 * One figure at thumbnail size.
 *
 * Drawn by the same code that draws it on the canvas, at the size the figure
 * says it wants, scaled to fit the tile: a picker that drew its own version of
 * each shape would eventually disagree with the canvas about what you chose.
 */
export function thumbnail(name, box = 64) {
	const { w, h } = figureSize(name);
	// A line is zero-high; give the thumbnail something to scale against.
	const fw = Math.max(w, 12);
	const fh = Math.max(h, 12);
	const k = Math.min(box / fw, box / fh);
	const dw = fw * k;
	const dh = fh * k;
	const root = svg('svg', {
		class: 'shape-thumb', viewBox: `0 0 ${box} ${box}`, 'aria-hidden': 'true',
	});
	const g = svg('g', {
		transform: `translate(${(box - dw) / 2} ${(box - dh) / 2})`,
	});
	for (const part of figureParts(name, dw, h === 0 ? 0 : dh)) {
		const role = ROLES[part.role] ?? ROLES.body;
		const node = part.ellipse
			? svg('ellipse', {
				cx: part.ellipse[0], cy: part.ellipse[1],
				rx: Math.abs(part.ellipse[2]), ry: Math.abs(part.ellipse[3]),
			})
			: svg('path', { d: part.d });
		node.setAttribute('class', `gdecor-part gdecor-${part.role}`);
		g.append(node);
		void role;
	}
	root.append(g);
	return root;
}

/**
 * @param {{onPick: (figure: string) => void}} hooks
 */
export function openShapePicker({ onPick }) {
	let query = '';

	openModal({
		title: 'Add a shape',
		subtitle: 'Drawn behind the blocks, and saved with the model. '
			+ 'Nothing in the model reads it.',
		build: (body) => {
			const search = el('input', {
				type: 'search',
				className: 'shape-search',
				placeholder: 'Search shapes — tree, arrow, box…',
				value: query,
				spellcheck: false,
			});
			search.addEventListener('input', () => {
				query = search.value.trim().toLowerCase();
				fill();
			});
			body.append(search);

			const list = el('div', { className: 'shape-groups' });
			body.append(list);

			const fill = () => {
				list.replaceChildren();
				let shown = 0;
				for (const group of FIGURE_GROUPS) {
					const names = Object.keys(FIGURES).filter((name) => {
						if (FIGURES[name].group !== group) return false;
						if (!query) return true;
						return `${name} ${FIGURES[name].label} ${group}`
							.toLowerCase().includes(query);
					});
					if (!names.length) continue;
					shown += names.length;
					const grid = el('div', { className: 'shape-grid' });
					for (const name of names) {
						const tile = el('button', {
							className: 'shape-tile',
							type: 'button',
							title: `${FIGURES[name].label} (${name})`,
						});
						tile.append(thumbnail(name));
						tile.append(el('span', { className: 'shape-tile-name' },
							FIGURES[name].label));
						tile.addEventListener('click', () => {
							closeModal();
							onPick(name);
						});
						grid.append(tile);
					}
					list.append(
						el('div', { className: 'shape-group-title' }, group),
						grid,
					);
				}
				if (!shown) {
					list.append(el('p', { className: 'insp-hint' },
						`Nothing matches “${search.value}”.`));
				}
			};
			fill();
			// The search box takes the caret, because typing is the fastest
			// way in for anyone who has been here before.
			requestAnimationFrame(() => search.focus());
		},
	});
}
