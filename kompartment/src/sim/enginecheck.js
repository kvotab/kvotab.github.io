/**
 * Check the run of a run an engine on this machine holds, made where the run
 * is held.
 *
 * Checked in the page, a run an engine holds has to come over first -- every
 * state at every output time, 140 MB on a 55,728-state assessment, and the
 * model built twice to read it -- and the careful run is then solved in the
 * browser while the engine that made the run in seconds waits. So the engine
 * is asked instead (a `check-run` job; see serve.py): it solves the careful
 * run beside the run it holds, sets the two against each other there and
 * sends back the report ./checkrun.js makes, nothing more. The run stays
 * where it is.
 *
 * What the engine cannot check -- a run no engine holds for the page any more
 * (the server answers 410), a server that does not know the job (400), an
 * engine that does not -- comes back as `{ elsewhere: true }`, and the page
 * checks the run itself.
 */

/** How often the job is asked how it is getting on, in milliseconds. */
export const CHECK_POLL = 250;

/**
 * A report as JSON carried it: a number that was not finite came as null, as
 * JSON.stringify writes one -- and a share that is not finite is Infinity, a
 * state that is a number in one run and not in the other.
 */
export function fromJson(report) {
	const inf = (v) => (v == null ? Infinity : v);
	return {
		...report,
		worst: inf(report.worst),
		moved: (report.moved ?? []).map((m) => ({ ...m, share: inf(m.share) })),
	};
}

/**
 * Asks the engine holding a run to check it, follows the job and fetches the
 * report.
 *
 * @param {object} o
 * @param {string} o.engine   the engine holding the run (`python`, `julia`, `cpp`)
 * @param {string} o.token    the page's token
 * @param {string} o.client   the page, as the server knows it
 * @param {string} o.run      the run, by the id the engine holds it under
 * @param {(p: {stage: string, fraction: number}) => void} [o.onProgress]
 *   `sending` until the engine takes it, then `building` and `solving`
 * @param {() => boolean} [o.isWanted]  false once the check is stopped or
 *   replaced: the job is cancelled at its next look
 * @returns {Promise<{report?: object, elsewhere?: boolean, why?: string, stopped?: boolean}>}
 */
export async function checkOnEngine({
	engine, token, client, run, onProgress = () => {}, isWanted = () => true,
	fetch: get = globalThis.fetch, poll = CHECK_POLL, wait = (ms) => new Promise((r) => { setTimeout(r, ms); }),
}) {
	const headers = { 'X-Kompartment-Token': token };
	const asked = await get('/engine/jobs', {
		method: 'POST',
		headers: { ...headers, 'Content-Type': 'application/json' },
		body: JSON.stringify({ kind: 'check-run', engine, client, model: null, options: { run } }),
	});
	const said = await asked.json().catch(() => ({}));
	if (asked.status === 410 || asked.status === 400) return { elsewhere: true, why: said.error ?? null };
	if (!asked.ok) throw new Error(said.error ?? `the server answered ${asked.status}`);
	const job = said.id;
	const cancel = () => get(`/engine/jobs/${job}/cancel`, { method: 'POST', headers }).catch(() => {});
	for (;;) {
		if (!isWanted()) { cancel(); return { stopped: true }; }
		await wait(poll);
		if (!isWanted()) { cancel(); return { stopped: true }; }
		const s = await (await get(`/engine/jobs/${job}`, { headers })).json();
		if (s.state === 'done') break;
		if (s.state === 'cancelled') return { stopped: true };
		if (s.state === 'error') {
			const message = s.error?.message ?? String(s.error ?? 'the check went wrong');
			// An engine that does not know the job: the page checks the run itself.
			if (/is not a kind of job/.test(message)) return { elsewhere: true, why: message };
			throw new Error(message);
		}
		if (!s.state) throw new Error(s.error ?? 'the server no longer knows the check');
		onProgress({
			stage: s.state === 'queued' ? 'sending'
				: s.stage === 'solving' || s.stage === 'writing' ? 'solving' : 'building',
			fraction: s.stage === 'writing' ? 1 : (Number.isFinite(s.fraction) ? s.fraction : 0),
		});
	}
	const got = await get(`/engine/jobs/${job}/archive`, { headers });
	if (!got.ok) throw new Error(`the engine kept no answer (the server answered ${got.status})`);
	return { report: fromJson(await got.json()) };
}
