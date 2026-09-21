/**
 * CSV, which is one rule: quote a field that would otherwise be read as more
 * than one.
 *
 * Its own module because two places write CSV and they must agree. `Results`
 * writes it for a run held in this process (`toCSV`, used by the tests and by
 * anything driving this tool headlessly); the page writes it for the run its
 * worker holds, where the numbers arrive as columns and there is no `Results`
 * object to ask. Living in the runner, this was reachable from the first and
 * not from the second: `src/ui/app.js` loads the runner only for the SciPy
 * solvers, on demand, so `csvCell` was not defined on the page at all and
 * every CSV export threw `ReferenceError` at the header line.
 */

/**
 * One CSV field. Quoted when it has to be -- RFC 4180: a comma, a quote or a
 * line break, and a quote inside doubled.
 *
 * Every indexed output's label holds a comma (`Soil [Cs-137, Lake]`), so this
 * is the difference between a spreadsheet reading one column per series and
 * splitting each label in two.
 */
export function csvCell(text) {
	const s = String(text ?? '');
	return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
