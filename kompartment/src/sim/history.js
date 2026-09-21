/**
 * What a block remembers.
 *
 * Five of Ecolego's block types are not functions of the state vector: they
 * depend on what has already happened. A min/max holds the largest value it has
 * seen, a delay reports what its target was an hour ago, a snapshot holds
 * whatever was true when an event last fired, a running mean divides an
 * integral by the time it covers. Everything else in this tool is recomputed
 * from `(t, y)` whenever it is wanted, and none of these can be.
 *
 * So they keep a history -- the (time, value) pairs recorded as the solver
 * accepted steps -- and read it back. That is what makes them work in the
 * two-phase arrangement the runner uses: the solver fills the history as it
 * goes, and afterwards the algebraic pass reads it at each output time, which
 * always lies at or before the last step taken.
 *
 * The growable array and the scalar recorder the generated code needs,
 * with the hold-below rule as `hold` and the recorder read as
 * `lerp`. Both are written here without a stateful cursor: reads
 * arrive in whatever order the solver's stages and the output grid ask for, and
 * a cursor that assumed otherwise would be wrong rather than merely slow.
 */

/** A growing list of (time, value) pairs, read back by time. */
export class History {
	constructor() {
		this.t = [];
		this.v = [];
	}

	get size() { return this.t.length; }

	clear() {
		this.t.length = 0;
		this.v.length = 0;
	}

	/** The last time recorded, or -Infinity when nothing has been. */
	get lastTime() { return this.t.length ? this.t[this.t.length - 1] : -Infinity; }

	/** The last value recorded, or 0 when nothing has been. */
	get lastValue() { return this.v.length ? this.v[this.v.length - 1] : 0; }

	/**
	 * Records a pair. Time never goes backwards here -- the solver only stores
	 * on an accepted step -- but a restart after an event can land on the time
	 * already stored, and that overwrites rather than adding a second point at
	 * the same instant, which neither reader would know how to choose between.
	 */
	add(time, value) {
		const n = this.t.length;
		if (n && time <= this.t[n - 1]) {
			this.t[n - 1] = time;
			this.v[n - 1] = value;
			return;
		}
		// A value that has not changed extends the run instead of starting a
		// third point in it. Both readers give the same answer either way --
		// `hold` returns the last point at or before the time, `lerp`
		// interpolates between two equal values -- and this is what keeps a
		// recorder that has settled from storing one pair per solver step for
		// the rest of the run. A stiff model takes hundreds of thousands of
		// steps, and a min/max that stopped changing at year 50 was keeping
		// every one of them.
		//
		// The *first* point of the run is kept, which is what makes it
		// lossless: collapsing onto the last would move the value's start
		// forward in time and change what `hold` answers before it.
		if (n >= 2 && this.v[n - 1] === value && this.v[n - 2] === value) {
			this.t[n - 1] = time;
			return;
		}
		this.t.push(time);
		this.v.push(value);
	}

	/**
	 * Drops what can no longer be read: everything more than two points before
	 * `before`, the two being kept so `lerp` still has a left-hand neighbour
	 * to interpolate from.
	 *
	 * Nothing calls this during a run, and nothing in the present arrangement
	 * can. A delay reads `t - lag` and never looks further back *while the
	 * solver is running* -- but the series a run reports are worked out
	 * afterwards, from the states, by `Results.seriesMany` in ../sim/runner.js,
	 * which asks every remembering block for its value at every output time
	 * from the first one on. A delay read at the first output time wants the
	 * history at `t_0 - lag`; a point dropped before then changes a reported
	 * number. So the history has to be whole until the run's results are
	 * discarded. The usual arrangement is the same shape: grow the arrays by
	 * half and never trim. The
	 * growth is one pair per accepted step for a delay whose target keeps
	 * moving; `add` above already folds a settled value into two points,
	 * which is what keeps a min/max or a snapshot from growing at all.
	 *
	 * The lag itself is no help in bounding it from here: it is an equation
	 * (whether the delay time is constant is a question the format asks,
	 * and the answer may be no), so the furthest back a delay can ask for is
	 * not known until it asks.
	 *
	 * Kept for the caller that can use it: one that evaluates and keeps each
	 * output row as the solver passes it, and so knows the oldest time it
	 * will ask for again.
	 */
	forget(before) {
		const cut = this._below(before);
		if (!(cut > 1)) return;
		this.t.splice(0, cut - 1);
		this.v.splice(0, cut - 1);
	}

	/**
	 * The index of the last point at or before `time`, or -1 when `time` is
	 * before the first. Bisection: reads come in the order the solver's stages
	 * and the output grid ask for them, not in order.
	 */
	_below(time) {
		let lo = 0;
		let hi = this.t.length - 1;
		if (hi < 0 || time < this.t[0]) return -1;
		while (lo < hi) {
			const mid = (lo + hi + 1) >> 1;
			if (this.t[mid] <= time) lo = mid; else hi = mid - 1;
		}
		return lo;
	}

	/**
	 * The value in force at `time`: a staircase that steps at each recorded
	 * point and is flat outside the range. the hold-below rule, which is
	 * what a snapshot holds and what every one of these blocks reads its own
	 * past with.
	 */
	hold(time) {
		const n = this.t.length;
		if (!n) return 0;
		if (time <= this.t[0]) return this.v[0];
		if (time >= this.t[n - 1]) return this.v[n - 1];
		return this.v[this._below(time)];
	}

	/**
	 * The value at `time`, straight between the two points either side, flat
	 * outside the range -- the recorder read, which is how a delay
	 * reads a moment the solver did not happen to step on.
	 */
	lerp(time) {
		const n = this.t.length;
		if (!n) return 0;
		if (time <= this.t[0]) return this.v[0];
		if (time >= this.t[n - 1]) return this.v[n - 1];
		const i = this._below(time);
		const t0 = this.t[i];
		const t1 = this.t[i + 1];
		if (t1 === t0) return this.v[i + 1];
		return this.v[i] + ((time - t0) / (t1 - t0)) * (this.v[i + 1] - this.v[i]);
	}
}

/**
 * One remembering block at one index tuple.
 *
 * The generated code holds these in `MEM` the way it holds lookup tables in
 * `TAB`, and calls `value` from the algebraic pass. The solver calls `store`
 * on every accepted step and `fire` when a discrete event it is attached to
 * goes off.
 *
 * @param {'min_max'|'running_mean'|'snapshot'|'delay'} kind
 */
export class Recorder {
	constructor(kind, { operation = 'max', recording = true } = {}) {
		this.kind = kind;
		this.history = new History();
		// +1 for a max, -1 for a min: the usual form is `max` or `min`
		// into the generated class, which is the same choice made earlier.
		this.sign = operation === 'min' ? -1 : 1;
		// A recorder with a start event does not record until it fires; one
		// without records from the first step. the min/max code generator decides
		// exactly this, at generation time, from whether the entry has a start
		// event.
		this.startsRecording = recording;
		this.recording = recording;
		// Running mean only: how much recorded time the integral covers, and
		// when the last step was, so the part of the current step already
		// elapsed can be added to it.
		this.totalTime = 0;
		this.lastTime = 0;
		// Running mean only: the integral as it stood when the mean was last
		// reset. The integral itself is a state the *solver* carries, so it
		// cannot be zeroed from here -- what can be done is to remember where
		// to measure from. See `fire` and `mean`.
		this.resetSum = 0;
	}

	/**
	 * Puts the recorder back to the start of a run.
	 *
	 * `seed` is the target's value at the start time for a min/max, a delay and
	 * a running mean, and the initial value for a snapshot -- in each case what
	 * the block reads before anything has happened to it.
	 */
	prime(t0, seed) {
		this.history.clear();
		this.recording = this.startsRecording;
		this.totalTime = 0;
		this.lastTime = t0;
		this.resetSum = 0;
		if (this.kind === 'running_mean') {
			this.history.add(t0, this.recording ? seed : 0);
			return;
		}
		this.history.add(t0, seed);
	}

	/**
	 * Records the step just accepted.
	 *
	 * `current` is the block's own value, not its target: a min/max records the
	 * extreme so far and a running mean the mean so far, which is what makes
	 * the history readable as the block's own past. A delay is the exception --
	 * it is its target's past that it reports -- and passes the target.
	 */
	store(t, current) {
		switch (this.kind) {
			case 'min_max':
				// Only where it changed: a max that has not moved for a
				// thousand steps is two points, not a thousand.
				if (current !== this.history.lastValue) this.history.add(t, current);
				break;
			case 'delay':
				this.history.add(t, current);
				break;
			case 'running_mean':
				if (this.recording) {
					this.history.add(t, current);
					this.totalTime += t - this.lastTime;
				}
				this.lastTime = t;
				break;
			default:
				break;
		}
	}

	/**
	 * A discrete event this recorder is attached to has gone off.
	 *
	 * `summed` is the running mean's integral as it stands, which only a
	 * caller holding the state vector can supply -- and which a reset needs,
	 * for the reason given below.
	 */
	fire(what, t, target, summed = 0) {
		switch (what) {
			case 'snapshot':
				this.history.add(t, target);
				break;
			case 'reset':
				this.history.add(t, target);
				// A min/max starts its extreme again from what it is watching,
				// and clearing the history does that. A running mean has to
				// start *two* things again: the integral and the time it
				// covers. The integral is a state the solver carries and
				// cannot be written from here, so the reset is recorded as an
				// offset instead -- the mean afterwards is the integral since
				// this instant over the time since this instant.
				//
				// Without this the event only added a point to the history: it
				// produced a visible spike at the reset and then no change at
				// all, so a mean "reset" at the start of a climate period went
				// on reporting the mean of the whole run.
				if (this.kind === 'running_mean') {
					this.resetSum = summed;
					this.totalTime = 0;
					this.lastTime = t;
				}
				break;
			case 'start':
				// Only the flag, and the clock. A start event sets the
				// recording flag and does nothing else, and the memory is
				// seeded with the target at t0 whether or not the block is
				// recording -- so a maximum that starts recording at year 5
				// reports the larger of the target at year 0 and everything
				// since, in the desktop tools as here. That is what they do, without
				// ambiguity, and it is kept: the seed is what the block reads
				// before the event, and after it the answer there is
				// `Math.max(lastValue, target)` with that seed as `lastValue`.
				// A model that wants the extreme to start again from the event
				// has the reset event for exactly that (see 'reset' above).
				//
				// The elapsed time a running mean divides by starts here, not
				// at the start of the simulation.
				this.recording = true;
				this.lastTime = t;
				break;
			case 'stop':
				this.recording = false;
				break;
			default:
				break;
		}
	}

	/**
	 * A min/max's value: the extreme of everything recorded and the target as
	 * it stands now.
	 *
	 * Behind the last step taken it is the recorded past, which is what makes
	 * the block readable at an output time after the solve, and what keeps a
	 * solver's rejected step from leaving a maximum that never happened.
	 */
	extreme(t, target) {
		if (t <= this.history.lastTime) return this.history.hold(t);
		if (!this.recording) return this.history.lastValue;
		const last = this.history.lastValue;
		return this.sign > 0 ? Math.max(last, target) : Math.min(last, target);
	}

	/** A snapshot's value: whatever was taken at the last event before `t`. */
	held(t) {
		return this.history.hold(t);
	}

	/** A delay's value: its target as it was `lag` ago. */
	delayed(t, lag) {
		return this.history.lerp(t - lag);
	}

	/**
	 * How much recorded time a running mean's integral covers at `t`: what it
	 * divides by, and so what the tangent of its value divides by too.
	 *
	 * While the recording is stopped it does not grow, because the integral
	 * above the line does not grow either. The usual implementation lets it grow and relies on
	 * `!Model._solving` to read the history instead once the run is over,
	 * which agrees with this to within one step while solving and not at all
	 * afterwards: a mean stopped at year 8 and read at year 9 came out half as
	 * large again as the mean actually recorded.
	 */
	elapsedAt(t) {
		return this.recording ? this.totalTime + t - this.lastTime : this.totalTime;
	}

	/**
	 * A running mean's value: the integral of the target over the recorded
	 * time, divided by that time.
	 *
	 * `summed` is the state the solver carries for it. Before any time has
	 * been recorded the mean of nothing is the target itself, which is what
	 * the running-mean code generator returns rather than dividing by zero.
	 */
	mean(t, summed, target) {
		if (t <= this.history.lastTime) return this.history.hold(t);
		const elapsed = this.elapsedAt(t);
		return elapsed > 0 ? (summed - this.resetSum) / elapsed : target;
	}
}
