/**
 * What an Ecolego export holds and what it leaves out, as the page shows it.
 *
 * Twice: in the Save dialog while the format is chosen, before anything is
 * written -- which is when the list is worth reading, because the model can
 * still be changed to fit -- and on the Build tab once the file is written,
 * as the record of what went out. The same report either way (see
 * `ExportReport` in ../io/ecoexport.js), in the tense of the moment.
 */

import { el } from './parts.js';

/**
 * @param {object} report  an `ExportReport`
 * @param {object} [opts]
 * @param {'before'|'after'} [opts.when]  whether the file is still to be written
 * @param {number} [opts.limit]  how many of each kind of thing left out to name
 * @param {{has: (name: string) => boolean, go: (name: string) => void}} [opts.reveal]
 *   what a name that is a block of the model does when clicked: takes the
 *   reader to it
 * @returns {Node[]}
 */
export function exportReportNodes(report, { when = 'after', limit = Infinity, reveal = null } = {}) {
	const before = when === 'before';
	const out = [];
	const counts = report.summary().split('\n')[0];
	out.push(el('p', { className: 'ir-counts' }, before ? counts.replace(/^Exported /, 'The project would hold ') : counts));

	const name = (n) => {
		if (!reveal?.has(n)) return el('b', {}, n);
		const link = el('button', { type: 'button', className: 'ir-link', title: `Go to ${n}` }, n);
		link.addEventListener('click', () => reveal.go(n));
		return link;
	};

	if (report.skipped.length) {
		const byType = new Map();
		for (const sk of report.skipped) {
			if (!byType.has(sk.type)) byType.set(sk.type, []);
			byType.get(sk.type).push(sk);
		}
		const list = el('ul', { className: 'ir-list' });
		for (const [type, items] of byType) {
			const shown = items.slice(0, limit);
			const li = el('li', {}, el('b', {}, `${items.length} ${type}`), ': ');
			shown.forEach((s, i) => {
				if (i) li.append('; ');
				li.append(name(s.name), ` (${s.why})`);
			});
			if (items.length > shown.length) li.append(`; and ${items.length - shown.length} more`);
			list.append(li);
		}
		out.push(
			el('p', { className: 'ir-warn' }, before
				? 'These have no place in an Ecolego project and would be left out, so the model in the file would '
					+ 'not be the whole of this one:'
				: 'These have no place in the file and were left out. The model in it is not the whole of this one:'),
			list,
		);
	} else if (before) {
		out.push(el('p', { className: 'ir-ok' }, 'Nothing is left out: every block goes into the project.'));
	}

	if (report.rewritten.length) {
		out.push(el('details', { className: 'ir-details', open: before && report.rewritten.length <= 4 },
			el('summary', {}, before
				? `${report.rewritten.length} thing(s) would be written in an equivalent form`
				: `${report.rewritten.length} thing(s) written in an equivalent form`),
			el('ul', { className: 'ir-list' }, ...report.rewritten.map((r) => el('li', {},
				el('b', {}, `${r.type} `), name(r.name), `: ${r.how}`)))));
	}

	if (report.renamed.length) {
		out.push(el('details', { className: 'ir-details' },
			el('summary', {}, `${report.renamed.length} renamed`),
			el('p', { className: 'ir-hint' }, report.renamed.map((r) => `${r.from} → ${r.to}`).join(', '))));
	}

	for (const w of report.warnings) out.push(el('p', { className: 'ir-warn' }, w));
	return out;
}
