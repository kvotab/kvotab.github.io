/*
  A live departure board for one SL commuter-train relation, drawn from the
  SL Transport API on Trafiklab.

  Two pages use it - uppsala.html and solna.html - and they differ only in
  their configuration: which site to ask, which of its departures count as
  "towards the other end", and which neighbouring stations make up the
  corridor the trains are drawn along. Everything else, from the fetch to the
  countdown to the wording of a delay, lives here once.

  The API:
    https://transport.integration.sl.se/v1/sites/{id}/departures
  Open, CORS-enabled and keyless, which is what makes a static page possible -
  there is nothing to leak. It returns at most three departures per line and
  direction however wide the forecast window (the OpenAPI spec says so, and
  T-Centralen with a 20-hour window confirmed it), so a board is always "the
  next three", and no parameter changes that.

  Where the trains are: SL's own API has no positions, so the board works two
  ways at once. Trafikverket serves live positions keyed by advertised train
  number, and SL's journey.id turns out to *be* that number with the date in
  front of it, so a departure this board already knows the line, destination
  and delay of can be joined to a real position exactly. Where no position is
  available the estimate below still runs - and it is what the whole board
  fell back on before any key existed. But the same journey carries the same journey.id at
  every station it calls at (10 of 10 checked), and each station reports SL's
  live forecast for it. Asking the corridor's stations together therefore gives
  each train's forecast at several points along the line, and its place right
  now is read off between the two it is between. Both directions and every SL
  line on the stretch are drawn, so the diagram shows how busy the track is;
  a terminating train, which has no departure row at its last station, is
  carried the final hop on a running time borrowed from a sibling.

  How fast to ask: the API serves a request every two seconds without
  complaint, but a minute of five-second sampling across twelve journeys saw
  no forecast change at all - SL revises in whole minutes, and only when a
  train is actually running late. Ten seconds is therefore plenty for the
  data; the motion in between is interpolation, redrawn every second and
  slid by CSS, and would be no smoother at any polling rate.

  The data are CC BY. The licence requires the page to say it is based on
  information from Trafiklab.se, with a link, and forbids keeping a copy
  beyond a cache - this module holds only recent responses, in memory.
*/
(function (global) {
  'use strict';

  const API = 'https://transport.integration.sl.se/v1/sites';

  const REFRESH_MS = 10 * 1000;
  /* On an error the interval doubles, up to this, and resets on success. */
  const BACKOFF_MAX_MS = 60 * 1000;
  const TICK_MS = 1000;
  /*
    The API returns at most three departures per line and direction whatever
    window is asked for, so this only decides how far ahead it is willing to
    look - and a board showing two trains because the third is beyond the
    window is a board hiding what somebody came to find out. Twenty hours is
    the API's own maximum: late in the evening the three next trains include
    tomorrow morning's, and they are shown as clock times rather than a count
    of minutes. Asking for a longer window costs no extra requests.
  */
  const FORECAST_MIN = 1200;
  /* Data older than this is refreshed at once, whatever the timers say. A
     laptop lid, a phone in a pocket, a throttled tab: the interval may not
     have fired, but the age of what is on screen is always known. */
  const STALE_MS = REFRESH_MS * 3;
  /* A tab left open is the expensive kind of nobody-looking: it is visible,
     it is on screen, and it polls all night. After this long with no pointer,
     key, scroll or touch the board stops asking and says so; anything at all
     starts it again. It is deliberately long, because a departure board is
     the sort of page a person watches without touching it. A page meant to
     run unattended on a wall passes idleMs: 0. */
  const IDLE_MS = 15 * 60 * 1000;
  /* The forecast at a stop is the departure. The train arrives a little
     before that and stands; the dot should too. Pendeltåg dwell is about half
     a minute, and on a two-minute hop that is a quarter of the run, so it is
     capped. */
  const DWELL_S = 30;
  /* Forecasts are remembered this long after a journey was last listed. */
  const MEMORY_MS = 60 * 60 * 1000;
  /* Live positions, when a trains endpoint is configured. Measured against
     Trafikverket: a given train's fix is revised every 5-20 s, and the Worker
     caches for 3, so asking faster returns the same answer twice. Motion
     between fixes is interpolation and a 1 s CSS transition, not polling. */
  const GPS_MS = 3 * 1000;
  /* A fix older than this is a train that has stopped reporting, not a train
     standing still, and is dropped rather than left sitting on the diagram. */
  const GPS_STALE_MS = 90 * 1000;
  /*
    How far off the drawn line a fix may be and still be this corridor's train.

    This was 3 km, inherited from the GTFS-RT days when a fix could not be
    tied to a journey at all and the allowance had to cover the bend of a rail
    the diagram draws straight. With positions now joined by train number, the
    real spread is measurable: across ten rounds of live sampling on both
    corridors, every train SL actually lists on the stretch projected within
    **0.43 km** of the line, while trains on neighbouring tracks sat at 1.96,
    2.17, 2.34 and 3.40 km. There is a clean gap between the two, and 3 km sat
    on the wrong side of it - which is why trains that are not on this track
    were being drawn as though they were.

    1.2 km is in that gap: near three times the widest genuine offset, and
    well under the nearest impostor.

    Off the *ends* of the line the allowance has to be tighter still, because
    there the distance is along the track rather than across it: a train a
    kilometre past the last station is a kilometre away from this stretch, not
    on it.
  */
  const GPS_CORRIDOR_KM = 1.2;
  const GPS_END_KM = 0.7;
  /*
    A fix and a forecast are the same train when they carry the same train
    number - no distance guessing is involved. SL's journey.id is the date
    followed by the five-digit advertised train number, and Trafikverket keys
    its positions by exactly that number: journey "2026091302272" is train
    2272 on 13 September 2026. Checked against live data from both APIs at
    once: 16 of 23 journeys on these corridors matched a position, and the
    seven that did not were services that had not departed yet.

    This replaced a nearest-fix-on-the-same-line-going-the-same-way match,
    which had to size itself against the corridor's median hop and could still
    pair a fix with the wrong train on a short hop. Identity beats proximity.
  */
  function trainNumberOf(journeyId) {
    const s = String(journeyId == null ? '' : journeyId);
    return /^\d{13}$/.test(s) ? String(parseInt(s.slice(8), 10)) : null;
  }

  /* The states a departure can be in, and what the board says about each.
     From the spec's departureStateEnum; the ones the API actually produced in
     a 600-departure sample were EXPECTED and ATSTOP, with real delays arriving
     as expected > scheduled rather than as a state. The rest are kept so a
     rare one reads as words rather than as an upper-case token. */
  const STATE_LABEL = {
    EXPECTED: null,
    NOTEXPECTED: 'Not confirmed',
    NOTCALLED: 'Not calling here',
    ATSTOP: 'At the platform',
    BOARDING: 'Boarding',
    BOARDINGCLOSED: 'Doors closed',
    DEPARTED: 'Departed',
    PASSED: 'Departed',
    ASSUMEDDEPARTED: 'Departed',
    MISSED: 'Departed',
    CANCELLED: 'Cancelled',
    INHIBITED: 'Cancelled',
    REPLACED: 'Replaced',
  };
  const GONE = new Set(['DEPARTED', 'PASSED', 'ASSUMEDDEPARTED', 'MISSED', 'NOTCALLED']);
  const CANCELLED = new Set(['CANCELLED', 'INHIBITED']);
  const AT_PLATFORM = new Set(['ATSTOP', 'BOARDING', 'BOARDINGCLOSED']);

  const esc = (v) => (typeof kvotEscapeHtml === 'function'
    ? kvotEscapeHtml(v)
    : String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));

  /* The API gives local wall-clock times without a zone ("2026-09-13T18:56:00").
     Parsed as local time, which is what they are; the visitor's clock is
     assumed to be in Sweden too, and the page says as much if the two disagree
     by more than a couple of minutes, since a countdown against the wrong
     clock is worse than none. */
  function parseLocal(iso) {
    if (!iso) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(iso);
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
  }
  const hhmm = (d) => d ? d.toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' }) : '';
  const hhmmss = (d) => d ? d.toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';

  function minutesUntil(when, now) {
    return Math.round((when - now) / 60000);
  }

  /* Great-circle distance between two sites, in km. The corridor is spaced
     by it so that a dot's speed across the screen means something. */
  /*
    Which way along a drawn segment a train is running: true when its compass
    bearing is within a right angle of the segment's own bearing, which is to
    say it is heading for the far end of the line.

    A function of its own, and exported, because the inline version read
    `diff > 90` - the exact opposite of the comment above it - and so drew
    every train it applied to backwards. It went unseen because a train
    matched to a departure takes its direction from SL's direction_code
    instead, so only trains the board could not name were reversed. Checked
    against six live trains of known direction, `diff < 90` agreed six times
    and `diff > 90` none.
  */
  function runsForward(bearing, segBearing) {
    if (typeof bearing !== 'number' || typeof segBearing !== 'number') return true;
    const diff = Math.abs(((bearing - segBearing + 540) % 360) - 180);
    return diff < 90;
  }

  function kmBetween(a, b) {
    const p = Math.PI / 180;
    const h = 0.5 - Math.cos((b.lat - a.lat) * p) / 2
      + Math.cos(a.lat * p) * Math.cos(b.lat * p) * (1 - Math.cos((b.lon - a.lon) * p)) / 2;
    return 12742 * Math.asin(Math.sqrt(h));
  }

  /* One departure, reduced to what the board needs. */
  function shape(dep) {
    const scheduled = parseLocal(dep.scheduled);
    const expected = parseLocal(dep.expected) || scheduled;
    const delayMin = (scheduled && expected) ? Math.round((expected - scheduled) / 60000) : 0;
    return {
      line: dep.line?.designation ?? '',
      destination: dep.destination ?? '',
      directionCode: dep.direction_code ?? null,
      journeyId: dep.journey?.id ?? null,
      platform: dep.stop_point?.designation ?? '',
      scheduled,
      expected,
      delayMin,
      state: dep.state || 'EXPECTED',
      journeyState: dep.journey?.state || '',
      prediction: dep.journey?.prediction_state || '',
      display: dep.display || '',
      deviations: (dep.deviations || []).map((d) => ({
        message: d.message || '',
        level: d.importance_level ?? 0,
        consequence: d.consequence || '',
      })),
    };
  }

  /*
    Where along the corridor a journey is right now, from its forecasts at the
    corridor's stations.

      { at: k }                          standing at station k
      { from: i, to: j, f, runSec }      between stations i and j, fraction f
                                         of the way from i, over a run of runSec
      { approaching: k, secs }           not yet at the first drawn station k;
                                         due there in secs
      null                               past the stretch, or nothing known

    `order` is the corridor's indices in the train's travel order - forward
    for one direction, reversed for the other - so both are one code path,
    and i/j come back as corridor indices whichever way the train goes.

    `times` includes forecasts remembered from earlier refreshes: a train that
    has left a station drops out of that station's list at once, and without
    the memory a train three minutes out of Uppsala looked as though it had
    not arrived yet. `runBetween(i, j)` supplies a hop's running time when the
    journey's own forecast at one end is missing, borrowed from a sibling that
    has both. That is what carries a terminating train into its last station,
    which never lists it as a departure at all.
  */
  function locate(times, states, now, runBetween, order) {
    const known = [];
    order.forEach((k, pos) => { if (times[k]) known.push({ k, pos, t: times[k], state: states[k] || '' }); });
    if (!known.length) return null;
    const standing = known.find((s) => AT_PLATFORM.has(s.state));
    if (standing) return { at: standing.k };
    const t = now.getTime();
    const first = known[0], last = known[known.length - 1];
    const hop = (run) => Math.min(DWELL_S * 1000, run * 0.25);

    if (t < first.t) {
      if (first.pos > 0) {
        const prev = order[first.pos - 1];
        const run = runBetween(prev, first.k);
        if (run && t >= first.t - run) {
          const f = Math.min(1, Math.max(0, (t - (first.t - run)) / Math.max(1, run - hop(run))));
          return { from: prev, to: first.k, f, runSec: (run - hop(run)) / 1000, inferred: true };
        }
      }
      return { approaching: first.k, secs: Math.round((first.t - t) / 1000) };
    }
    for (let n = 0; n < known.length - 1; n++) {
      const a = known[n], b = known[n + 1];
      if (t >= a.t && t < b.t) {
        const run = b.t - a.t;
        const f = Math.min(1, (t - a.t) / Math.max(1, run - hop(run)));
        return { from: a.k, to: b.k, f, runSec: (run - hop(run)) / 1000 };
      }
    }
    /* Past the last forecast. If a drawn station lies beyond it, the train is
       on its way there - the terminus case. */
    if (last.pos < order.length - 1) {
      const next = order[last.pos + 1];
      const run = runBetween(last.k, next);
      if (run && t < last.t + run) {
        const f = Math.min(1, (t - last.t) / Math.max(1, run - hop(run)));
        return { from: last.k, to: next, f, runSec: (run - hop(run)) / 1000, inferred: true };
      }
      if (run && t < last.t + run + 60 * 1000) return { at: next };
      return null;
    }
    if (t < last.t + 60 * 1000) return { at: last.k };
    return null;
  }

  function mountBoard(root, config) {
    if (!root) return null;
    /* Mounting twice on one element would leave the first board's timers
       repainting over the second. The element remembers its board. */
    if (root.__slBoard && typeof root.__slBoard.stop === 'function') root.__slBoard.stop();
    /* trainsUrl points at the /trains endpoint of the Worker in
       workers/sl-vehicles.js, which holds the Trafikverket key. Without it the
       board behaves exactly as before, on forecasts alone - live positions are
       an improvement on the estimate, never something the board needs.

       It can also be set from the browser's own storage, which is how to try a
       Worker before committing its URL to the page:

         localStorage.setItem('kvot-sl-trains', 'https://…workers.dev/trains')

       Storage rather than a query parameter on purpose: a URL in the address
       bar is a link somebody can send to somebody else, and a page that
       fetches whatever a link tells it to is a page doing as it is told by a
       stranger. */
    const cfg = Object.assign({ refreshMs: REFRESH_MS, forecast: FORECAST_MIN, corridor: [], directionCode: null, trainsUrl: null, idleMs: IDLE_MS }, config);
    if (!cfg.trainsUrl) {
      try { cfg.trainsUrl = localStorage.getItem('kvot-sl-trains') || null; } catch (e) { /* storage unavailable */ }
    }

    /* The corridor always includes the home station; positions along it are
       cumulative distance, normalised to 0..1. */
    const corridor = cfg.corridor.length ? cfg.corridor : [{ siteId: cfg.siteId, name: cfg.fromName }];
    const n = corridor.length;
    const homeIndex = Math.max(0, corridor.findIndex((s) => s.siteId === cfg.siteId));
    const hasGeometry = corridor.every((s) => typeof s.lat === 'number' && typeof s.lon === 'number');
    const cumulative = [0];
    for (let i = 1; i < n; i++) cumulative.push(cumulative[i - 1] + (hasGeometry ? kmBetween(corridor[i - 1], corridor[i]) : 1));
    const span = cumulative[n - 1] || 1;
    const xOf = (i) => cumulative[i] / span;
    const FORWARD = corridor.map((_, i) => i);
    const REVERSE = FORWARD.slice().reverse();
    const farEnd = corridor[n - 1] ? corridor[n - 1].name : cfg.toName;
    const nearEnd = corridor[0] ? corridor[0].name : cfg.fromName;

    /*
      Projecting a fix onto the drawn line. The corridor is treated as a chain
      of straight segments in a local kilometre frame centred on it - over
      seventy kilometres of Uppland the error from ignoring the curvature of
      the earth is metres, far below the three kilometres of slack the match
      already allows.

      Returns how far along the corridor the point falls (0..1), how far it
      lies off the line, and the bearing of the segment it fell on, which is
      what tells a northbound train from a southbound one.
    */
    const originLat = corridor.reduce((a, s) => a + s.lat, 0) / (n || 1);
    const originLon = corridor.reduce((a, s) => a + s.lon, 0) / (n || 1);
    const kx = 111.32 * Math.cos(originLat * Math.PI / 180), ky = 110.57;
    const toXY = (lat, lon) => ({ x: (lon - originLon) * kx, y: (lat - originLat) * ky });
    const nodes = hasGeometry ? corridor.map((s) => toXY(s.lat, s.lon)) : [];

    function projectOnCorridor(lat, lon) {
      if (!hasGeometry || nodes.length < 2) return null;
      const p = toXY(lat, lon);
      let best = null;
      for (let i = 0; i < nodes.length - 1; i++) {
        const a = nodes[i], b = nodes[i + 1];
        const dx = b.x - a.x, dy = b.y - a.y;
        const len2 = dx * dx + dy * dy;
        const t = len2 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2)) : 0;
        const cx = a.x + t * dx, cy = a.y + t * dy;
        const off = Math.hypot(p.x - cx, p.y - cy);
        if (!best || off < best.off) {
          const along = cumulative[i] + t * (cumulative[i + 1] - cumulative[i]);
          /* Compass bearing of this segment, 0 = north, clockwise. */
          const segBearing = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
          /* A point beyond either end of the drawn line projects onto the
             end itself, because t is clamped - so without this flag every
             train south of Stockholm City would be drawn standing at
             Stockholm City, piled on top of each other. */
          const beyond = (i === 0 && t === 0) || (i === nodes.length - 2 && t === 1);
          best = { off, u: along / span, alongKm: along, segBearing, segment: i, beyond };
        }
      }
      return best;
    }

    let departures = [];
    let stopDeviations = [];
    let fixes = [];             // the last live positions, already projected
    let fixesAt = null;         // when they arrived
    let fixesError = null;
    let gpsTimer = null;
    let journeys = new Map();   // journeyId -> { line, directionCode, destination, stops: shape|null[], sample }
    const memory = new Map();   // journeyId -> { times: number[], line, directionCode, destination, seen }
    let fetchedAt = null;
    let lastError = null;
    let backoffMs = cfg.refreshMs;
    let refreshTimer = null;
    let tickTimer = null;
    let inFlight = null;
    const reducedMotion = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

    root.classList.add('sl-board');
    if (reducedMotion) root.classList.add('sl-reduced');
    root.innerHTML = `
      <div class="sl-head">
        <div class="sl-relation">
          <span class="sl-from">${esc(cfg.fromName)}</span>
          <span class="sl-arrow" aria-hidden="true">→</span>
          <span class="sl-to">${esc(cfg.toName)}</span>
        </div>
        <div class="sl-meta">
          <span class="sl-live" id="sl-live" aria-live="polite"></span>
          <span class="sl-clock" id="sl-clock"></span>
        </div>
      </div>
      <div class="sl-body" id="sl-body" aria-live="polite" aria-busy="true">
        <div class="sl-empty">Fetching departures…</div>
      </div>
      ${n > 1 ? `
      <div class="sl-track" id="sl-track" aria-label="Where the trains are along the line">
        <svg class="sl-track-svg" id="sl-track-svg" viewBox="0 0 1000 232" preserveAspectRatio="none" role="img"></svg>
        <div class="sl-legend" id="sl-legend"></div>
        <div class="sl-track-note" id="sl-track-note"></div>
      </div>` : ''}
      <div class="sl-deviations" id="sl-deviations" hidden></div>
      <div class="sl-foot">
        <button type="button" class="sl-refresh" id="sl-refresh">Refresh now</button>
        <span class="sl-note" id="sl-note"></span>
      </div>
      <p class="sl-attribution">
        Real-time data: this page is based on information retrieved from
        <a href="https://www.trafiklab.se/" target="_blank" rel="noopener noreferrer">Trafiklab.se</a>
        (SL Transport API, CC&nbsp;BY). Times are SL's own forecasts and can change.
        Train positions come from
        <a href="https://www.trafikverket.se/" target="_blank" rel="noopener noreferrer">Trafikverket</a>
        (TrainPosition).
      </p>`;

    const $ = (id) => root.querySelector('#' + id);

    /* One refresh asks every corridor station at once. The home station's
       answer feeds the board; all of them feed the map of journeys. */
    async function refresh() {
      if (inFlight) return inFlight;
      $('sl-live').textContent = 'Updating…';
      const fetchSite = (siteId) => fetch(`${API}/${siteId}/departures?transport=TRAIN&forecast=${cfg.forecast}`,
        { cache: 'no-store', headers: { Accept: 'application/json' } })
        .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });

      inFlight = Promise.allSettled(corridor.map((s) => fetchSite(s.siteId)))
        .then((results) => {
          const home = results[homeIndex];
          if (home.status !== 'fulfilled') throw home.reason || new Error('home station unavailable');
          const all = (home.value.departures || []).map(shape);
          departures = all.filter(cfg.keep).sort((a, b) => a.expected - b.expected);
          stopDeviations = (home.value.stop_deviations || []).map((d) => ({
            message: d.message || '', level: d.importance_level ?? 0,
          }));

          /* Every train of every line, both directions, keyed by journey with
             a slot per station. A station that failed to answer leaves its
             slots empty; the interpolation bridges it. */
          const next = new Map();
          results.forEach((res, k) => {
            if (res.status !== 'fulfilled') return;
            for (const raw of res.value.departures || []) {
              const d = shape(raw);
              if (!d.journeyId || !d.line) continue;
              let j = next.get(d.journeyId);
              if (!j) { j = { line: d.line, directionCode: d.directionCode, destination: d.destination, stops: new Array(n).fill(null), sample: d }; next.set(d.journeyId, j); }
              j.stops[k] = d;
              /* Prefer the home station's own row as the sample - that is where
                 the platform and the delay matter to the reader. */
              if (k === homeIndex) j.sample = d;
            }
          });
          /* Only trains that run on this track. Line 43 shares Stockholm
             City and Odenplan with line 40 and then branches off; it would
             otherwise be drawn heading for Solna, where it never arrives. The
             lines that call at the home station define the track. */
          const homeLines = new Set(all.map((d) => d.line));
          for (const [id, j] of next) if (!homeLines.has(j.line)) next.delete(id);
          journeys = next;
          const stamp = Date.now();
          for (const [id, j] of next) {
            let m = memory.get(id);
            if (!m) { m = { times: new Array(n).fill(null), line: j.line, directionCode: j.directionCode, destination: j.destination, seen: stamp }; memory.set(id, m); }
            m.seen = stamp;
            j.stops.forEach((d, k) => { if (d) m.times[k] = d.expected.getTime(); });
          }
          for (const [id, m] of memory) {
            const latest = Math.max(0, ...m.times.filter(Boolean));
            if (stamp - m.seen > MEMORY_MS || (latest && stamp - latest > MEMORY_MS)) memory.delete(id);
          }
          fetchedAt = new Date();
          lastError = null;
          backoffMs = cfg.refreshMs;
        })
        .catch((err) => {
          lastError = err;
          backoffMs = Math.min(BACKOFF_MAX_MS, backoffMs * 2);
          if (typeof reportFailure === 'function') reportFailure('sl-board:refresh', err);
        })
        .finally(() => {
          inFlight = null;
          render();
          schedule();
        });
      return inFlight;
    }

    /*
      The GPS fixes, on their own faster clock. One request, answered by the
      Worker from a two-second cache, so polling it costs the upstream quota
      nothing beyond that one fetch however many people are watching.

      A failure here is quiet by design: the diagram falls back to the
      forecast positions it has always drawn, and the note says which it is
      showing. Real-time positions are an improvement on the estimate, never
      a thing the board depends on.
    */
    async function refreshTrains() {
      if (!cfg.trainsUrl) return;
      const url = new URL(cfg.trainsUrl, location.href);
      if (hasGeometry) {
        const lats = corridor.map((c) => c.lat), lons = corridor.map((c) => c.lon);
        const pad = GPS_CORRIDOR_KM / 100;
        url.searchParams.set('bbox', [Math.min(...lats) - pad, Math.min(...lons) - pad,
          Math.max(...lats) + pad, Math.max(...lons) + pad].map((v) => v.toFixed(4)).join(','));
      }
      url.searchParams.set('maxAgeSec', String(Math.round(GPS_STALE_MS / 1000)));
      try {
        const res = await fetch(url, { cache: 'no-store', headers: { Accept: 'application/json' } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        fixes = (data.trains || []).map((t) => {
          const on = projectOnCorridor(t.lat, t.lon);
          if (!on || on.off > (on.beyond ? GPS_END_KM : GPS_CORRIDOR_KM)) return null;
          /* Which way along the drawn line: compare the train's own compass
             bearing with the bearing of the segment it is on. Within a right
             angle of it means it is running towards the far end. */
          const forward = runsForward(t.bearing, on.segBearing);
          if (typeof t.ageSec === 'number' && t.ageSec * 1000 > GPS_STALE_MS) return null;
          const number = String(t.number == null ? '' : t.number);
          if (!number) return null;
          return {
            number, id: 'tv:' + number,
            u: on.u, alongKm: on.alongKm, offKm: on.off, forward,
            /* Trafikverket reports km/h already, and omits the field for
               roughly half the trains - absent is not the same as nought, so
               an unknown speed stays null and simply is not shown. */
            kmh: typeof t.speed === 'number' ? Math.round(t.speed) : null,
            /* Trafikverket reports a stopped train as 0 or 1 km/h and
               sometimes 2 while a coupling settles, so anything at walking
               pace counts as standing. Drawing "~1 km/h" under a train at a
               platform is noise dressed up as precision. */
            standing: typeof t.speed === 'number' && t.speed < 3,
            ageSec: typeof t.ageSec === 'number' ? t.ageSec : null,
          };
        }).filter(Boolean);
        fixesAt = new Date();
        fixesError = null;
      } catch (err) {
        fixesError = err;
        /* Fixes go stale rather than lingering: better an honest estimate
           than a position frozen where a train used to be. */
        if (fixesAt && Date.now() - fixesAt > GPS_STALE_MS) fixes = [];
        if (typeof ignoreFailure === 'function') ignoreFailure('sl-board:trains', err);
      }
      render();
    }

    /* A timeout chain rather than an interval, so the cadence can stretch
       while the API is unhappy and snap back when it is not. */
    function schedule() {
      if (refreshTimer) clearTimeout(refreshTimer);
      if (tickTimer === null) return;                       // stopped
      refreshTimer = setTimeout(refresh, backoffMs);
    }

    /*
      A clock of digits that each take the width they feel like is a clock that
      twitches once a second - and it drags whatever sits beside it along. This
      font has no tabular figures: "1" measures 2.22px where "3" and "8"
      measure 6.02px, so hh:mm:ss swings 22.5px between 11:11:11 and 23:33:33.
      `font-variant-numeric: tabular-nums` is set and computes, but the font
      offers no `tnum` feature for it to switch on, so it does nothing at all.

      Each character therefore gets a cell of its own, the width of the widest
      digit: what tabular figures would have done, done in the layout instead.
      Cells are reused across ticks so a clock running all day is a handful of
      textContent writes rather than eight elements a second.
    */
    function paintClock(el, text) {
      if (el.childElementCount !== text.length) {
        el.textContent = '';
        for (let i = 0; i < text.length; i++) el.appendChild(document.createElement('span'));
      }
      for (let i = 0; i < text.length; i++) {
        const cell = el.children[i], ch = text[i];
        if (cell.textContent !== ch) cell.textContent = ch;
        const cls = ch === ':' ? 'sl-clock-sep' : 'sl-clock-digit';
        if (cell.className !== cls) cell.className = cls;
      }
    }

    function render() {
      const now = new Date();
      paintClock($('sl-clock'), hhmmss(now));
      $('sl-body').setAttribute('aria-busy', inFlight ? 'true' : 'false');

      /* Liveness, in the corner: when we last heard, and whether we are
         hearing at all. A board that quietly stops updating and keeps
         showing stale minutes is the one failure a departure board must
         never have - so data past its age is refetched here, in the tick,
         regardless of whether the refresh timer ever fired. */
      const ageMs = fetchedAt ? now - fetchedAt : null;
      if (ageMs !== null && ageMs > STALE_MS && !inFlight && active()) refresh();
      const ageSec = ageMs !== null ? Math.round(ageMs / 1000) : null;
      if (lastError && !fetchedAt) {
        $('sl-live').textContent = 'No connection';
        $('sl-live').className = 'sl-live sl-live-bad';
      } else if (lastError) {
        $('sl-live').textContent = `Last update ${hhmm(fetchedAt)} — retrying`;
        $('sl-live').className = 'sl-live sl-live-stale';
      } else if (ageSec !== null) {
        $('sl-live').textContent = ageSec < 3 ? 'Live' : `Updated ${ageSec}s ago`;
        $('sl-live').className = 'sl-live' + (ageMs > STALE_MS ? ' sl-live-stale' : ' sl-live-ok');
      }

      if (!fetchedAt) {
        $('sl-body').innerHTML = lastError
          ? `<div class="sl-empty sl-error">Could not reach the SL Transport API (${esc(lastError.message)}).<br>It will be retried automatically.</div>`
          : '<div class="sl-empty">Fetching departures…</div>';
        $('sl-note').textContent = '';
        return;
      }

      /* Departures that have already gone are dropped from the board rather
         than shown as negative minutes; the API keeps them for a moment. */
      const upcoming = departures.filter((d) => !GONE.has(d.state) && minutesUntil(d.expected, now) >= -1);

      /* The API attaches a station's notice - a lift out of order - to every
         departure's own deviations, so the same sentence arrived on the hero
         and on each row. A message every upcoming train carries is the
         station's, shown once below; one that only some carry is that
         train's, and stays on it. */
      const shared = upcoming.length
        ? upcoming.map((d) => new Set(d.deviations.map((x) => x.message)))
            .reduce((acc, set) => new Set([...acc].filter((m) => set.has(m))))
        : new Set();
      const own = (d) => (shared.size ? Object.assign({}, d, { deviations: d.deviations.filter((x) => !shared.has(x.message)) }) : d);
      if (!upcoming.length) {
        $('sl-body').innerHTML = `<div class="sl-empty">No ${esc(cfg.toName)}-bound trains found${cfg.forecast >= 600 ? '' : ` in the next ${Math.round(cfg.forecast / 60)} hours`}.</div>`;
      } else {
        const [next, ...rest] = upcoming;
        $('sl-body').innerHTML = renderHero(own(next), now) + (rest.length ? `<ol class="sl-rest">${rest.map((d) => renderRow(own(d), now)).join('')}</ol>` : '');
      }

      if ($('sl-track')) renderTrack(now);

      const seen = new Set();
      const messages = [];
      for (const d of stopDeviations) if (d.message && !seen.has(d.message)) { seen.add(d.message); messages.push(d); }
      for (const m of shared) if (m && !seen.has(m)) { seen.add(m); messages.push({ message: m, level: 0 }); }
      const devBox = $('sl-deviations');
      if (messages.length) {
        devBox.hidden = false;
        devBox.innerHTML = `<h2 class="sl-dev-title">At ${esc(cfg.fromName)}</h2>` +
          messages.map((d) => `<p class="sl-dev${d.level >= 5 ? ' sl-dev-major' : ''}">${esc(d.message)}</p>`).join('');
      } else {
        devBox.hidden = true;
        devBox.innerHTML = '';
      }

      /* If the visitor's clock disagrees with the API's idea of "now" by a
         lot, every countdown is wrong by that much. The API gives no server
         time, but a first departure that is already minutes in the past while
         still EXPECTED is the tell. */
      const first = upcoming[0];
      const skew = first && first.state === 'EXPECTED' ? minutesUntil(first.expected, now) : 0;
      $('sl-note').textContent = skew < -2
        ? 'Your device clock seems to be ahead of Swedish time; countdowns may be off.'
        : `Next ${upcoming.length} departure${upcoming.length === 1 ? '' : 's'} · line 40 · data every ${Math.round(backoffMs / 1000)} s`;
    }

    /*
      The line diagram. Stations sit at their real spacing. Trains heading
      towards the far end run above the rail, left to right; trains heading
      the other way run below it, right to left, each with a chevron for its
      direction. Every SL line on the stretch is drawn in its own colour, and
      the ring round a train says whether it is on time. Dots are keyed by
      journey so the browser slides an existing one rather than redrawing it -
      that, with a one-second linear transition on the transform, is the whole
      animation; the data behind it changes in whole minutes.
    */
    const RAIL_Y = 100, X0 = 60, X1 = 940, LANE = 30, LIFT = 28;
    function renderTrack(now) {
      const svg = $('sl-track-svg');
      const px = (u) => X0 + u * (X1 - X0);
      if (!svg.querySelector('.sl-stations')) {
        const rows = [];
        corridor.forEach((s, i) => { rows[i] = i > 0 && px(xOf(i)) - px(xOf(i - 1)) < 150 && rows[i - 1] === 0 ? 1 : 0; });
        const stations = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        stations.setAttribute('class', 'sl-stations');
        stations.innerHTML =
          `<line class="sl-rail" x1="${X0}" y1="${RAIL_Y}" x2="${X1}" y2="${RAIL_Y}"/>` +
          `<text class="sl-lane-label" x="${X0}" y="${RAIL_Y - LANE - 34}" text-anchor="start">→ towards ${esc(farEnd)}</text>` +
          `<text class="sl-lane-label" x="${X1}" y="${RAIL_Y + LANE + 87}" text-anchor="end">← towards ${esc(nearEnd)}</text>` +
          corridor.map((s, i) => {
            const x = px(xOf(i)), home = i === homeIndex;
            const anchor = i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle';
            return `<g class="sl-station${home ? ' sl-station-home' : ''}">` +
              `<circle cx="${x}" cy="${RAIL_Y}" r="${home ? 9 : 6}"/>` +
              `<text x="${x}" y="${RAIL_Y + LANE + 49 + rows[i] * 19}" text-anchor="${anchor}">${esc(s.name)}</text></g>`;
          }).join('');
        svg.appendChild(stations);
        const layer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        layer.setAttribute('class', 'sl-trains');
        svg.appendChild(layer);
      }
      const trains = svg.querySelector('.sl-trains');

      /* Running time between two adjacent stations, from any journey that has
         forecasts at both, whichever way it was travelling - the same line
         first, any line failing that. */
      const runBetween = (i, k) => {
        let any = null;
        for (const m of memory.values()) {
          if (m.times[i] && m.times[k]) {
            const run = Math.abs(m.times[k] - m.times[i]);
            if (run > 0) { if (m.line === '40') return run; any = any ?? run; }
          }
        }
        return any;
      };

      const placed = [];
      /*
        A GPS fix beats an estimate, so a train that reports its position is
        drawn where it says it is, at the speed it says it is doing. The
        forecast journeys are still computed - they carry the delay, the
        destination and the punctuality ring, which the position feed does
        not have - and each is matched to the nearest fix on the same line
        going the same way. A journey with no fix is still drawn, from the
        forecast, exactly as before.
      */
      const live = fixes;
      const claimed = new Set();
      /* One lookup by train number: no radius, no tie-break, no chance of
         lending a fix to the train behind it. */
      const byNumber = new Map();
      for (const f of live) byNumber.set(f.number, f);

      const ids = new Set([...journeys.keys(), ...memory.keys()]);
      for (const id of ids) {
        const j = journeys.get(id), m = memory.get(id);
        if (!m) continue;
        const forward = cfg.directionCode === null || m.directionCode === cfg.directionCode;
        const states = (j ? j.stops : []).map((d) => (d ? d.state : ''));
        const where = locate(m.times, states, now, runBetween, forward ? FORWARD : REVERSE);
        /* Found by number, so this is this journey's own train or nothing. */
        const fix = byNumber.get(trainNumberOf(id)) || null;
        if (!where && !fix) continue;
        const sample = j ? j.sample : null;
        let x, kmh = null, standing = false, approaching = null, label;
        if (fix) {
          /* Identity, not proximity, so the fix is believed over the estimate
             even where the forecasts still have the train approaching: it is
             on the drawn stretch, and this is where it says it is. The lane
             still comes from the journey's own direction_code, which is
             steadier than a compass bearing taken while standing at a
             platform. */
          claimed.add(fix.id);
          x = px(fix.u);
          kmh = fix.kmh;
          standing = fix.standing;
          label = fix.standing ? 'standing' : 'position reported by the train';
        } else if ('approaching' in where) {
          if (where.secs > 20 * 60 || where.approaching === homeIndex) continue;
          x = px(xOf(where.approaching)) + (forward ? -34 : 34);
          approaching = where.secs;
          label = `due at ${corridor[where.approaching].name} in ${Math.max(1, Math.round(where.secs / 60))} min`;
        } else if ('at' in where) {
          x = px(xOf(where.at)); standing = true; label = `at ${corridor[where.at].name}`;
        } else {
          x = px(xOf(where.from) + (xOf(where.to) - xOf(where.from)) * where.f);
          const km = hasGeometry ? Math.abs(cumulative[where.to] - cumulative[where.from]) : null;
          kmh = km !== null && where.runSec > 0 ? Math.round(km / (where.runSec / 3600)) : null;
          /* A hop is measured departure to departure, so a long stand at the
             far station - Odenplan holds trains for a minute or two - lands
             in the run and drags the implied speed down to walking pace.
             Dwell cannot be told from running from these forecasts, so a
             figure that low is not shown; the dot still moves. */
          if (kmh !== null && kmh < 25) kmh = null;
          label = `${corridor[where.from].name} → ${corridor[where.to].name}`;
        }
        const delay = sample ? sample.delayMin : 0;
        const punctual = sample && CANCELLED.has(sample.state) ? 'cancel' : delay >= 2 ? 'late' : delay <= -2 ? 'early' : sample ? 'ontime' : 'unknown';
        placed.push({ id: fix ? 'gps:' + fix.id : 'fc:' + id, x, forward, standing, approaching,
          label, kmh, delay, punctual, number: trainNumberOf(id),
          line: m.line, dest: m.destination || (forward ? farEnd : nearEnd), live: !!fix });
      }

      /* Fixes nothing on the board accounts for - a line the departure list
         does not cover, or a train between two of our journeys - are drawn on
         their own, with what the feed knows and nothing it does not. */
      for (const v of live) {
        if (claimed.has(v.id)) continue;
        /* Trafikverket carries every train on the rails, so these are the
           ones this board's departure lists do not cover: SJ, Mälartåg,
           Upptåget, freight. That is the answer to whether the track is busy,
           and it is why the position source matters - a road vehicle could
           never appear here.

           Their line and destination are genuinely unknown; the train number
           is not, so the label says that and which way it is running. Naming
           the end of the drawn line as the destination would be inventing
           one. */
        placed.push({ id: 'gps:' + v.id, x: px(v.u), forward: v.forward, standing: v.standing,
          approaching: null, label: v.standing ? 'standing' : 'position reported by the train',
          kmh: v.kmh, delay: 0, punctual: 'unknown', line: null, number: v.number,
          dest: null, heading: v.forward ? farEnd : nearEnd, live: true });
      }

      /* Within a lane, two trains close together would overprint; the later
         one is lifted a tier further from the rail. */
      for (const lane of [true, false]) {
        const group = placed.filter((p) => p.forward === lane).sort((a, b) => a.x - b.x);
        for (let i = 1; i < group.length; i++) if (group[i].x - group[i - 1].x < 48) group[i].lift = ((group[i - 1].lift || 0) + 1) % 2;
      }

      const seenIds = new Set();
      for (const p of placed) {
        seenIds.add(p.id);
        let g = trains.querySelector(`[data-key="${CSS.escape(p.id)}"]`);
        if (!g) {
          g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
          g.setAttribute('data-key', p.id);
          g.innerHTML = `<title></title>` +
            `<rect class="sl-train-body" x="-20" y="-13" width="40" height="26" rx="7"/>` +
            `<text class="sl-train-line" y="5" text-anchor="middle"></text>` +
            `<path class="sl-train-dir"/>` +
            `<text class="sl-train-speed" text-anchor="middle"></text>`;
          trains.appendChild(g);
        }
        const dir = p.forward ? 1 : -1;
        const y = RAIL_Y - dir * (LANE + (p.lift ? LIFT : 0));
        g.setAttribute('transform', `translate(${p.x.toFixed(1)} ${y})`);
        g.setAttribute('class', `sl-train sl-line-${/^\d+$/.test(p.line) ? p.line : 'other'} sl-${p.punctual}`
          + (p.standing ? ' sl-train-standing' : '') + (p.approaching !== null ? ' sl-train-approaching' : '')
          + (p.live ? ' sl-train-live' : '') + (p.forward ? ' sl-lane-a' : ' sl-lane-b')
          + (p.line ? '' : ' sl-train-unnamed'));
        /* With no line, the train number is what there is to show, and four
           digits need a smaller face than a two-digit line to fit the dot. */
        g.querySelector('.sl-train-line').textContent = p.line || p.number || '';
        /* A chevron on the leading edge, pointing the way the train goes. */
        g.querySelector('.sl-train-dir').setAttribute('d', p.forward ? 'M22,-6 L29,0 L22,6' : 'M-22,-6 L-29,0 L-22,6');
        const speed = g.querySelector('.sl-train-speed');
        speed.setAttribute('y', p.forward ? -20 : 30);
        speed.textContent = p.approaching !== null ? `in ${Math.max(1, Math.round(p.approaching / 60))} min`
          : p.punctual === 'late' ? `+${p.delay} min${p.kmh !== null && !p.standing ? ` · ${p.live ? '' : '~'}${p.kmh} km/h` : ''}`
          /* A reported speed is exact; only an inferred one gets a tilde. */
          : (p.standing || p.kmh === null ? '' : `${p.live ? '' : '~'}${p.kmh} km/h`);
        const who = !p.line ? `Train ${p.number}, towards ${p.heading}`
          : p.dest ? `Line ${p.line} to ${p.dest}` : `Line ${p.line}, towards ${p.heading}`;
        g.querySelector('title').textContent =
          `${who}: ${p.label}` + (p.kmh !== null && !p.standing && p.approaching === null ? `, ${p.live ? '' : 'about '}${p.kmh} km/h` : '')
          + (p.punctual === 'late' ? `, ${p.delay} min late` : p.punctual === 'early' ? `, ${-p.delay} min early` : p.punctual === 'cancel' ? ', cancelled' : p.punctual === 'ontime' ? ', on time' : '');
      }
      for (const g of [...trains.children]) if (!seenIds.has(g.getAttribute('data-key'))) g.remove();

      /* A train with no line contributes no key of its own; null would throw
         out of the comparator, and there is no line to name. */
      const lines = [...new Set(placed.map((p) => p.line).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'sv', { numeric: true }));
      $('sl-legend').innerHTML =
        lines.map((l) => `<span class="sl-key"><i class="sl-key-line sl-line-${/^\d+$/.test(l) ? l : 'other'}">${esc(l)}</i> line ${esc(l)}</span>`).join('') +
        (placed.some((p) => !p.line) ? `<span class="sl-key"><i class="sl-key-line sl-line-other">#</i> other train</span>` : '') +
        `<span class="sl-key"><i class="sl-key-ring sl-ontime"></i> on time</span>` +
        `<span class="sl-key"><i class="sl-key-ring sl-late"></i> late</span>` +
        `<span class="sl-key"><i class="sl-key-ring sl-cancel"></i> cancelled</span>`
        + (placed.some((p) => p.live) ? `<span class="sl-key"><i class="sl-key-ring sl-key-live"></i> live GPS</span>` : '');
      const a = placed.filter((p) => p.forward && p.approaching === null).length;
      const b = placed.filter((p) => !p.forward && p.approaching === null).length;
      const coming = placed.length - a - b;
      const parts = [];
      if (a) parts.push(`${a} towards ${farEnd}`);
      if (b) parts.push(`${b} towards ${nearEnd}`);
      if (coming) parts.push(`${coming} approaching`);
      const liveCount = placed.filter((p) => p.live).length;
      const source = !cfg.trainsUrl
        ? " Positions and speeds are estimated from SL's forecasts at each station."
        : fixesError && !liveCount
          ? " Live positions are unavailable, so these are estimated from SL's forecasts."
          : liveCount === placed.length && liveCount
            ? ' Positions and speeds are reported by the trains themselves.'
            : liveCount
              ? ` ${liveCount} of these report their own position and speed; the rest are estimated from SL's forecasts.`
              : " Positions and speeds are estimated from SL's forecasts at each station.";
      $('sl-track-note').textContent = (parts.length ? `${placed.length} train${placed.length === 1 ? '' : 's'}: ${parts.join(', ')}.` : 'No train on this stretch right now.') + source;
    }

    function badge(d) {
      if (CANCELLED.has(d.state)) return '<span class="sl-badge sl-badge-cancel">Cancelled</span>';
      if (d.delayMin >= 2) return `<span class="sl-badge sl-badge-late">+${d.delayMin} min</span>`;
      if (d.delayMin <= -2) return `<span class="sl-badge sl-badge-early">${d.delayMin} min</span>`;
      const label = STATE_LABEL[d.state];
      if (label) return `<span class="sl-badge">${esc(label)}</span>`;
      if (d.prediction === 'LOSTCONTACT' || d.prediction === 'UNRELIABLE') return '<span class="sl-badge sl-badge-warn">Position uncertain</span>';
      return '<span class="sl-badge sl-badge-ok">On time</span>';
    }

    /* Under two minutes the count is shown to the second: that is when it is
       being watched, and a number that visibly moves is what "live" means. */
    function countdown(d, now) {
      if (CANCELLED.has(d.state)) return { big: '—', small: 'cancelled' };
      if (AT_PLATFORM.has(d.state)) return { big: 'Now', small: 'at the platform' };
      const sec = Math.round((d.expected - now) / 1000);
      if (sec <= 0) return { big: 'Now', small: 'departing' };
      if (sec < 120) return { big: `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`, small: 'min:sec' };
      const m = Math.round(sec / 60);
      if (m < 60) return { big: String(m), small: 'minutes' };
      /* Past an hour a count of minutes stops meaning anything, so the clock
         time is shown instead. With a twenty-hour window that time is often
         tomorrow's, and "04:26" seen at half past eleven at night reads as
         four hours ago unless the day is said out loud. */
      const midnight = (t) => { const x = new Date(t); x.setHours(0, 0, 0, 0); return x.getTime(); };
      const days = Math.round((midnight(d.expected) - midnight(now)) / 86400000);
      return { big: hhmm(d.expected), small: 'departure', day: days };
    }

    function renderHero(d, now) {
      const c = countdown(d, now);
      const cancelled = CANCELLED.has(d.state);
      return `
        <div class="sl-hero${cancelled ? ' sl-hero-cancel' : ''}">
          <div class="sl-count">
            <span class="sl-count-big">${esc(c.big)}</span>
            <span class="sl-count-small">${esc(c.day ? (c.day === 1 ? 'tomorrow' : `in ${c.day} days`) : c.small)}</span>
          </div>
          <div class="sl-details">
            <div class="sl-line-row">
              <span class="sl-line">${esc(d.line)}</span>
              <span class="sl-dest">${esc(d.destination)}</span>
              ${badge(d)}
            </div>
            <div class="sl-times">
              <span class="sl-time-label">Scheduled</span>
              <span class="sl-time${d.delayMin >= 2 ? ' sl-time-struck' : ''}">${hhmm(d.scheduled)}</span>
              ${d.delayMin >= 2 || d.delayMin <= -2 ? `<span class="sl-time-label">Expected</span><span class="sl-time sl-time-strong">${hhmm(d.expected)}</span>` : ''}
              ${d.platform ? `<span class="sl-time-label">Platform</span><span class="sl-platform">${esc(d.platform)}</span>` : ''}
            </div>
            ${d.deviations.length ? `<div class="sl-row-dev">${d.deviations.map((x) => esc(x.message)).join('<br>')}</div>` : ''}
          </div>
        </div>`;
    }

    function renderRow(d, now) {
      const c = countdown(d, now);
      const unit = c.day ? (c.day === 1 ? ' tomorrow' : ` in ${c.day} days`)
        : (c.big === 'Now' || CANCELLED.has(d.state) || c.small !== 'minutes') ? '' : ' min';
      return `
        <li class="sl-row${CANCELLED.has(d.state) ? ' sl-row-cancel' : ''}">
          <span class="sl-row-count">${esc(c.big)}<small>${unit}</small></span>
          <span class="sl-row-time">${hhmm(d.scheduled)}${d.delayMin >= 2 ? ` <span class="sl-row-exp">→ ${hhmm(d.expected)}</span>` : ''}</span>
          <span class="sl-row-dest"><span class="sl-line sl-line-sm">${esc(d.line)}</span> ${esc(d.destination)}</span>
          <span class="sl-row-plat">${d.platform ? 'Pl. ' + esc(d.platform) : ''}</span>
          <span class="sl-row-badge">${badge(d)}</span>
          ${d.deviations.length ? `<span class="sl-row-dev">${d.deviations.map((x) => esc(x.message)).join('<br>')}</span>` : ''}
        </li>`;
    }

    /* --- Is anybody actually looking? ---------------------------------

       Every fetch this board makes is one somebody's quota pays for, and the
       positions endpoint is asked every three seconds, so none of it happens unless
       a person could see the result. Three things have to be true at once,
       and each is a different way of not looking:

         visible    the tab is in front              visibilitychange
         onScreen   the board is in the viewport     IntersectionObserver
         !idle      somebody touched the page        pointer/key/scroll/touch

       The first two are certain: nobody can see a background tab or a board
       scrolled half a page down. The third is only a guess, which is why the
       window is a quarter of an hour and why the faintest movement ends it.

       A stopped board says it has stopped. Silently showing minute counts
       that are no longer being checked is the one thing a departure board
       must never do, so pausing greys it and names the reason. */

    let onScreen = true;
    let lastActivity = Date.now();
    let pausedReason = null;
    /* idleMs: 0 disables the idle gate entirely, for an unattended screen. */
    const idleMs = cfg.idleMs > 0 ? cfg.idleMs : Infinity;
    const active = () => !document.hidden && onScreen && (Date.now() - lastActivity) <= idleMs;

    function start() {
      stop();
      pausedReason = null;
      root.classList.remove('sl-paused');
      tickTimer = setInterval(tick, TICK_MS);
      refresh();
      if (cfg.trainsUrl) {
        refreshTrains();
        gpsTimer = setInterval(refreshTrains, GPS_MS);
      }
    }
    function stop() {
      if (refreshTimer) clearTimeout(refreshTimer);
      if (tickTimer) clearInterval(tickTimer);
      if (gpsTimer) clearInterval(gpsTimer);
      refreshTimer = null; tickTimer = null; gpsTimer = null;
    }

    function paintPaused() {
      const reason = (document.hidden || !onScreen) ? 'not in view' : 'idle';
      /* Only on a change: a mouse moving over an off-screen board would
         otherwise rewrite this on every event. */
      if (pausedReason === reason) return;
      pausedReason = reason;
      root.classList.add('sl-paused');
      $('sl-body').setAttribute('aria-busy', 'false');
      const el = $('sl-live');
      el.className = 'sl-live sl-live-paused';
      el.textContent = 'Paused \u2014 ' + reason;
    }

    /* One place decides whether the timers run, so three independent signals
       cannot leave them in a state none of them meant. */
    function sync() {
      if (active()) { if (tickTimer === null) start(); return; }
      if (tickTimer !== null) stop();
      paintPaused();
    }

    /* The one-second tick costs nothing and touches no network, so it doubles
       as the thing that notices the visitor has gone quiet. */
    function tick() {
      if (!active()) { sync(); return; }
      render();
    }

    const onActivity = () => {
      lastActivity = Date.now();
      /* Only worth a call when stopped; while running there is nothing to do
         but note the time, and this fires on every mouse move. */
      if (tickTimer === null) sync();
    };
    const onVisibility = () => sync();
    /* pageshow fires right after load and focus when the window is given
       focus, so on a plain page load both arrive on top of the first fetch.
       Data a few seconds old does not need asking for again - and a board
       that sync() has just started has already fetched. */
    const onWake = () => {
      lastActivity = Date.now();
      const wasStopped = tickTimer === null;
      sync();
      if (wasStopped || tickTimer === null) return;
      if (!(fetchedAt && Date.now() - fetchedAt < 5000)) refresh();
      if (cfg.trainsUrl && !(fixesAt && Date.now() - fixesAt < 5000)) refreshTrains();
    };

    /* A board below the fold is about to be read, so it is woken slightly
       before it arrives rather than starting blank under the visitor's eye. */
    let observer = null;
    if (typeof IntersectionObserver === 'function') {
      observer = new IntersectionObserver((entries) => {
        for (const e of entries) if (e.target === root) onScreen = e.isIntersecting;
        sync();
      }, { rootMargin: '150px' });
      observer.observe(root);
    }

    const ACTIVITY = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart', 'scroll'];
    for (const name of ACTIVITY) global.addEventListener(name, onActivity, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);
    global.addEventListener('online', onWake);
    global.addEventListener('pageshow', onWake);
    global.addEventListener('focus', onWake);
    /* An explicit click is proof somebody is looking. Resuming already
       fetches, and asking again in the same instant would spend exactly the
       quota this section exists to save. */
    $('sl-refresh').addEventListener('click', () => {
      lastActivity = Date.now();
      const wasStopped = tickTimer === null;
      sync();
      if (!wasStopped && tickTimer !== null) { refresh(); refreshTrains(); }
    });

    sync();
    const handle = {
      /* The configuration as it was resolved, so a console or a test can
         re-mount the same board with one thing changed. */
      config: cfg,
      refresh, refreshTrains, start,
      /* For a test or a console: whether the board considers itself watched,
         and why it stopped if it did. */
      isActive: active,
      get paused() { return pausedReason; },
      get polling() { return tickTimer !== null; },
      stop() {
        stop();
        if (observer) observer.disconnect();
        for (const name of ACTIVITY) global.removeEventListener(name, onActivity);
        document.removeEventListener('visibilitychange', onVisibility);
        global.removeEventListener('online', onWake);
        global.removeEventListener('pageshow', onWake);
        global.removeEventListener('focus', onWake);
      },
    };
    root.__slBoard = handle;
    return handle;
  }

  global.KVOT_SL = { mountBoard, shape, parseLocal, locate, kmBetween, STATE_LABEL,
    trainNumberOf, runsForward,
    REFRESH_MS, STALE_MS, FORECAST_MIN, GPS_MS, GPS_CORRIDOR_KM, IDLE_MS };
})(window);
