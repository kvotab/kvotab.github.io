/*
  A Cloudflare Worker that turns Trafiklab's GTFS-Realtime vehicle feed into
  plain JSON the departure boards can read.

  Why it exists at all: kvotab.se is served by GitHub Pages, which runs no
  code. The GTFS-RT feed needs an API key, and a key in a static page is a key
  anybody can take. This Worker holds the key, fetches the feed, and serves the
  result with CORS - so the pages stay static and the key never leaves the
  edge.

  It also spares the quota. Trafiklab's Bronze tier is 30 000 calls a month,
  which is about 17 hours of two-second polling; Silver is 2 000 000, which
  covers it. Either way the number of upstream fetches must not grow with the
  number of visitors, so the upstream response is cached for two seconds and
  every request inside that window is served from it.

  Deploy, from the command line (wrangler.toml beside this file)
  --------------------------------------------------------------
    cd workers
    npx wrangler login
    npx wrangler secret put TRAFIKLAB_KEY
    npx wrangler deploy

  Or through the dashboard, where the section is account-level and has been
  called both "Workers & Pages" and "Compute (Workers)": Create application
  -> Workers -> Start with Hello World, then replace the code with this file
  and add TRAFIKLAB_KEY under Settings -> Variables and Secrets.

  Either way the result is a URL ending in .workers.dev; the boards want it
  with /vehicles on the end. No domain needs to be on Cloudflare for this.

  No build step, no npm: the GTFS-RT protobuf is decoded by hand below, which
  is a page of code and avoids a bundler.

  Endpoints
  ---------
    GET /trains                        <- what the boards use
      ?bbox=minLat,minLon,maxLat,maxLon optional, clips to a rectangle
      ?number=2272,2977                 optional, advertised train numbers
      ?maxAgeSec=120                    optional, how stale a fix may be

    { "timestamp": 1789330848, "count": 27, "cached": true,
      "trains": [ { number, operational, lat, lon, speed, bearing, at,
                    ageSec } ] }

    speed is km/h, as Trafikverket reports it. `number` is the advertised
    train number, which is what SL's journey.id ends with: journey
    "2026091302272" is the date plus train 2272. That is the join, and it
    means a board can attach a real position to a departure it already knows
    the line, destination and delay of, with no guessing by distance.

    GET /vehicles                      <- older, GTFS-RT, of little use
      ?mode=TRAIN|BUS|TRAM|METRO|SHIP   optional, repeatable, default TRAIN
      ?bbox=minLat,minLon,maxLat,maxLon optional, clips to a rectangle
      ?line=40,41                       optional, designations

    { "timestamp": 1789323813,
      "vehicles": [ { id, line, routeId, tripId, lat, lon, bearing, speed,
                      status, timestamp, mode } ] }

    speed is metres per second, exactly as the vehicle reported it.

    Its trouble is that the feed names almost no lines: 7 of 554 vehicles
    carried a route_id in a live sample. Keeping it costs nothing, but
    /trains is the one that works.

  Data: Trafikverket's TrainPosition (key: TRAFIKVERKET_KEY) for positions;
  Trafiklab GTFS Regional Realtime (TRAFIKLAB_KEY) and SL's keyless Transport
  API for the older path. Trafiklab's licence asks that a product say it is
  based on information from Trafiklab.se; the pages do.

  Both keys are set with `npx wrangler@3 secret put <NAME>` and live with
  Cloudflare, never in this file and never in the repo - the site is served
  from GitHub Pages, where everything is public.
*/

const FEED = 'https://opendata.samtrafiken.se/gtfs-rt/sl/VehiclePositions.pb';
const LINES = 'https://transport.integration.sl.se/v1/lines?transport_authority_id=1';

/* Two seconds is the feed's own update interval, so a shorter cache would buy
   nothing but quota. */
const FEED_TTL = 2;
/* Line designations change with a timetable, not with a train. */
const LINES_TTL = 3600;

const MODES = { 0: 'TRAM', 1: 'METRO', 2: 'TRAIN', 3: 'BUS', 4: 'FERRY', 7: 'FUNICULAR' };
/* GTFS-RT VehicleStopStatus. */
const STATUS = { 0: 'INCOMING_AT', 1: 'STOPPED_AT', 2: 'IN_TRANSIT_TO' };

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Max-Age': '86400',
};

/* ── A protobuf reader, only as much as GTFS-RT needs ────────────────────── */

function reader(bytes) {
  let p = 0;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const self = {
    get done() { return p >= bytes.length; },
    /* Multiplication rather than shifts: a uint64 timestamp overflows the
       32-bit bitwise operators. */
    varint() {
      let value = 0, shift = 0, byte;
      do {
        byte = bytes[p++];
        value += (byte & 0x7f) * Math.pow(2, shift);
        shift += 7;
      } while (byte & 0x80 && shift < 64);
      return value;
    },
    float() { const v = view.getFloat32(p, true); p += 4; return v; },
    chunk() { const len = self.varint(); const out = bytes.subarray(p, p + len); p += len; return out; },
    text() { return new TextDecoder().decode(self.chunk()); },
    skip(wire) {
      if (wire === 0) self.varint();
      else if (wire === 1) p += 8;
      /* The length must be read into a variable first: `p += self.varint()`
         captures the old p before varint() advances it, so every skipped
         length-delimited field lands one byte short and the next tag is
         read out of the middle of this one. */
      else if (wire === 2) { const len = self.varint(); p += len; }
      else if (wire === 5) p += 4;
      else throw new Error('unknown wire type ' + wire);
    },
  };
  return self;
}

/* Walk one message, handing each (field, wire, reader) to `on`; anything the
   caller does not claim is skipped. */
function walk(bytes, on) {
  const r = reader(bytes);
  while (!r.done) {
    const tag = r.varint();
    const field = tag >>> 3, wire = tag & 7;
    if (!on(field, wire, r)) r.skip(wire);
  }
}

function parsePosition(bytes) {
  const out = {};
  walk(bytes, (field, wire, r) => {
    if (wire !== 5) return false;
    if (field === 1) { out.lat = r.float(); return true; }      // latitude
    if (field === 2) { out.lon = r.float(); return true; }      // longitude
    if (field === 3) { out.bearing = r.float(); return true; }  // bearing
    if (field === 5) { out.speed = r.float(); return true; }    // metres/second
    return false;
  });
  return out;
}

function parseTrip(bytes) {
  const out = {};
  walk(bytes, (field, wire, r) => {
    if (field === 1 && wire === 2) { out.tripId = r.text(); return true; }
    if (field === 5 && wire === 2) { out.routeId = r.text(); return true; }
    if (field === 6 && wire === 0) { out.directionId = r.varint(); return true; }
    return false;
  });
  return out;
}

function parseVehicleDescriptor(bytes) {
  const out = {};
  walk(bytes, (field, wire, r) => {
    if (field === 1 && wire === 2) { out.id = r.text(); return true; }
    if (field === 2 && wire === 2) { out.label = r.text(); return true; }
    return false;
  });
  return out;
}

function parseVehiclePosition(bytes) {
  const out = {};
  walk(bytes, (field, wire, r) => {
    if (field === 1 && wire === 2) { Object.assign(out, parseTrip(r.chunk())); return true; }
    if (field === 2 && wire === 2) { Object.assign(out, parsePosition(r.chunk())); return true; }
    if (field === 4 && wire === 0) { out.status = STATUS[r.varint()] ?? null; return true; }
    if (field === 5 && wire === 0) { out.timestamp = r.varint(); return true; }
    if (field === 8 && wire === 2) { out.vehicle = parseVehicleDescriptor(r.chunk()); return true; }
    return false;
  });
  return out;
}

/* FeedMessage { header = 1; repeated FeedEntity entity = 2 }
   FeedEntity  { id = 1; ... vehicle = 4 } */
function parseFeed(bytes) {
  const vehicles = [];
  walk(bytes, (field, wire, r) => {
    if (field !== 2 || wire !== 2) return false;
    walk(r.chunk(), (ef, ew, er) => {
      if (ef === 1 && ew === 2) { vehicles.push({ entityId: er.text() }); return true; }
      if (ef === 4 && ew === 2) {
        const v = parseVehiclePosition(er.chunk());
        if (vehicles.length && !vehicles[vehicles.length - 1].lat) Object.assign(vehicles[vehicles.length - 1], v);
        else vehicles.push(v);
        return true;
      }
      return false;
    });
    return true;
  });
  return vehicles.filter((v) => typeof v.lat === 'number' && typeof v.lon === 'number');
}

/* ── Line designations, from SL's keyless endpoint ───────────────────────── */

/*
  GTFS-RT gives a route_id like 9011001004000000, which is no use on a board.
  SL's /v1/lines answers with the same value as `gid` beside designation "40",
  so the two join without GTFS Static and without a second key.
*/
async function lineNames() {
  const res = await fetch(LINES, { cf: { cacheTtl: LINES_TTL, cacheEverything: true } });
  if (!res.ok) return new Map();
  const data = await res.json();
  const map = new Map();
  for (const group of Object.values(data)) {
    if (!Array.isArray(group)) continue;
    for (const line of group) {
      if (line && line.gid && line.designation) map.set(String(line.gid), String(line.designation));
    }
  }
  return map;
}

/* ── Trafikverket, for trains ────────────────────────────────────────────── */

/*
  The GTFS-RT feed above turned out not to name its lines: of 554 vehicles
  carrying a position, 7 had a route_id. The trip_id it does carry
  (14010000666894129) is a GTFS *static* trip id, so naming a line that way
  needs the static dataset, a daily zip and somewhere to keep it.

  Trafikverket answers the question directly, and better for this particular
  use. SL's departures give journey.id "2026091302272", which is the date
  followed by the five-digit advertised train number - and Trafikverket serves
  live positions keyed by exactly that number. So a board can join what it
  already knows (line, destination, direction, delay) to a real position with
  no heuristics at all. It is also trains only, which removes the risk of
  drawing a bus on the E4 as a train, and it covers Uppsala and the other
  operators sharing the rails, which an SL feed does not.
*/
const TRAINS_API = 'https://api.trafikinfo.trafikverket.se/v2/data.json';
/* Measured: a given train's position is revised every 5-20 s, so polling
   faster than this only spends somebody's allowance. */
const TRAINS_TTL = 3;
/* Trafikverket keeps a train's last known position long after it stops
   reporting - one train in a live sample was 21 hours stale - so old fixes
   are dropped rather than drawn standing on the track. */
const TRAIN_MAX_AGE_S = 120;

/* The namespace is spelled with ä escapes rather than literal characters so
   the query cannot be broken by a file being re-saved in another encoding;
   Trafikverket matches it byte for byte. */
const TRAIN_NS = 'järnväg.trafikinfo';

/* INCLUDE keeps the answer to the six fields a board uses; without it the
   reply is several times the size for no gain. */
const trainsQuery = (key) =>
  '<REQUEST><LOGIN authenticationkey="' + key + '"/>' +
  '<QUERY objecttype="TrainPosition" namespace="' + TRAIN_NS + '" schemaversion="1.1" limit="6000">' +
  '<FILTER><EQ name="Status.Active" value="true"/></FILTER>' +
  '<INCLUDE>Train.AdvertisedTrainNumber</INCLUDE>' +
  '<INCLUDE>Train.OperationalTrainNumber</INCLUDE>' +
  '<INCLUDE>Position.WGS84</INCLUDE>' +
  '<INCLUDE>Speed</INCLUDE><INCLUDE>Bearing</INCLUDE><INCLUDE>TimeStamp</INCLUDE>' +
  '</QUERY></REQUEST>';

const POINT = /POINT \((-?[\d.]+) (-?[\d.]+)\)/;

/*
  Trafikverket needs POST, and Cloudflare's edge cache keys only on GET, so
  `cf: { cacheTtl }` does nothing here and the cache is driven by hand against
  a synthetic GET key. Without it every visitor's poll would be its own call
  upstream, which is the one thing this Worker exists to prevent.
*/
async function trainPositions(env, ctx) {
  const cache = caches.default;
  const key = new Request('https://trains.cache.invalid/positions', { method: 'GET' });
  const hit = await cache.match(key);
  if (hit) return { trains: await hit.json(), cached: true };

  const res = await fetch(TRAINS_API, {
    method: 'POST',
    headers: { 'Content-Type': 'text/xml' },
    body: trainsQuery(env.TRAFIKVERKET_KEY),
  });
  if (!res.ok) throw new Error('Trafikverket returned ' + res.status);
  const data = await res.json();
  const result = (data.RESPONSE && data.RESPONSE.RESULT && data.RESPONSE.RESULT[0]) || {};
  if (result.ERROR) throw new Error('Trafikverket: ' + JSON.stringify(result.ERROR).slice(0, 200));

  const trains = [];
  for (const row of result.TrainPosition || []) {
    const m = POINT.exec((row.Position && row.Position.WGS84) || '');
    if (!m) continue;
    const number = String((row.Train && row.Train.AdvertisedTrainNumber) || '');
    if (!number) continue;
    const at = row.TimeStamp ? Date.parse(row.TimeStamp) : NaN;
    trains.push({
      number,
      /* Freight and empty stock run without an advertised number; the
         operational one is kept so such a train can still be told apart. */
      operational: String((row.Train && row.Train.OperationalTrainNumber) || '') || null,
      lon: Math.round(parseFloat(m[1]) * 1e6) / 1e6,
      lat: Math.round(parseFloat(m[2]) * 1e6) / 1e6,
      /* Trafikverket reports km/h, not metres per second. */
      speed: typeof row.Speed === 'number' ? row.Speed : null,
      bearing: typeof row.Bearing === 'number' ? row.Bearing : null,
      /* The fix's own time, never an age: an age computed here would itself
         age by up to TRAINS_TTL seconds while the answer sits in the cache. */
      at: Number.isFinite(at) ? at : null,
    });
  }
  ctx.waitUntil(cache.put(key, new Response(JSON.stringify(trains), {
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=' + TRAINS_TTL },
  })));
  return { trains, cached: false };
}

async function handleTrains(url, env, ctx) {
  if (!env.TRAFIKVERKET_KEY) return bad('TRAFIKVERKET_KEY is not set on this Worker', 503);

  let trains, cached;
  try {
    ({ trains, cached } = await trainPositions(env, ctx));
  } catch (err) {
    return bad(err.message, 502);
  }

  const box = (url.searchParams.get('bbox') || '').split(',').map(Number);
  const clip = box.length === 4 && box.every(Number.isFinite) ? box : null;
  const asked = Number(url.searchParams.get('maxAgeSec'));
  const maxAge = Number.isFinite(asked) && asked > 0 ? asked : TRAIN_MAX_AGE_S;
  const wanted = new Set((url.searchParams.get('number') || '').split(',').map((x) => x.trim()).filter(Boolean));

  const now = Date.now();
  const out = [];
  let stale = 0, outside = 0;
  for (const t of trains) {
    const ageSec = t.at === null ? null : Math.round((now - t.at) / 1000);
    /* A fix from the future by more than a minute is a clock problem, not a
       train, and is dropped for the same reason a stale one is. */
    if (ageSec === null || ageSec > maxAge || ageSec < -60) { stale++; continue; }
    if (clip && (t.lat < clip[0] || t.lat > clip[2] || t.lon < clip[1] || t.lon > clip[3])) { outside++; continue; }
    if (wanted.size && !wanted.has(t.number)) continue;
    out.push({ number: t.number, operational: t.operational, lat: t.lat, lon: t.lon,
               speed: t.speed, bearing: t.bearing, at: t.at, ageSec });
  }

  if (url.searchParams.get('debug')) {
    return jsonResponse({
      source: 'trafikverket', cached,
      activeTrains: trains.length,
      droppedStale: stale, droppedOutsideBox: outside,
      returned: out.length, bbox: clip, maxAgeSec: maxAge,
      sample: out.slice(0, 6),
    });
  }
  return jsonResponse({ timestamp: Math.floor(now / 1000), count: out.length, cached, trains: out },
                      'public, max-age=' + TRAINS_TTL);
}

/* ── The handler ─────────────────────────────────────────────────────────── */

function bad(message, status = 500) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS },
  });
}

function jsonResponse(body, cacheControl) {
  const headers = { 'Content-Type': 'application/json; charset=utf-8', ...CORS };
  if (cacheControl) headers['Cache-Control'] = cacheControl;
  return new Response(JSON.stringify(body, null, 1), { headers });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
    if (request.method !== 'GET') return bad('GET only', 405);

    const url = new URL(request.url);
    /* /trains is the one the boards use; /vehicles is the older GTFS-RT path,
       kept because it works, though it can name almost no lines. */
    if (url.pathname.replace(/\/+$/, '').endsWith('/trains')) return handleTrains(url, env, ctx);

    if (!env.TRAFIKLAB_KEY) return bad('TRAFIKLAB_KEY is not set on this Worker', 503);
    const modes = new Set((url.searchParams.getAll('mode').join(',') || 'TRAIN')
      .split(',').map((s) => s.trim().toUpperCase()).filter(Boolean));
    const wanted = new Set((url.searchParams.get('line') || '').split(',').map((s) => s.trim()).filter(Boolean));
    const box = (url.searchParams.get('bbox') || '').split(',').map(Number);
    const clip = box.length === 4 && box.every(Number.isFinite) ? box : null;

    let feed, names;
    try {
      [feed, names] = await Promise.all([
        /* Trafiklab refuses the feed outright without this header:
             406 {"errorMessage":"This API must be called with the HTTP-header
                  'Accept-Encoding' set to 'gzip' or 'deflate'"}
           Asking for it explicitly can mean the runtime hands back the body
           still compressed rather than unwrapping it, which is why the gzip
           magic number is checked below. */
        fetch(`${FEED}?key=${encodeURIComponent(env.TRAFIKLAB_KEY)}`, {
          headers: { 'Accept-Encoding': 'gzip' },
          cf: { cacheTtl: FEED_TTL, cacheEverything: true },
        }),
        lineNames(),
      ]);
    } catch (err) {
      return bad(`upstream unreachable: ${err.message}`, 502);
    }
    if (!feed.ok) {
      /* 403 here almost always means the key is wrong or over quota, which is
         worth saying plainly rather than as a blank 500. */
      return bad(`Trafiklab returned ${feed.status}`, feed.status === 403 ? 403 : 502);
    }

    let raw = new Uint8Array(await feed.arrayBuffer());
    /* 1f 8b is the gzip magic number. A runtime that decompressed for us
       leaves protobuf here instead, which starts 0a. */
    const wasGzip = raw.length > 2 && raw[0] === 0x1f && raw[1] === 0x8b;
    if (wasGzip) {
      try {
        const stream = new Response(raw).body.pipeThrough(new DecompressionStream('gzip'));
        raw = new Uint8Array(await new Response(stream).arrayBuffer());
      } catch (err) {
        return bad(`feed arrived gzipped and could not be unwrapped: ${err.message}`, 502);
      }
    }
    let parsed;
    try {
      parsed = parseFeed(raw);
    } catch (err) {
      return bad(`could not decode the feed: ${err.message}`, 502);
    }

    /*
      ?debug=1 reports what each stage saw, so an empty answer can be traced
      without redeploying blind. It names no key and returns no position - only
      counts and a couple of route ids, which are public identifiers.
    */
    if (url.searchParams.get('debug')) {
      const routeIds = [...new Set(parsed.map((v) => String(v.routeId)))];
      const named = routeIds.filter((id) => names.has(id));
      /* The first bytes say at once whether this is a protobuf at all: a
         GTFS-RT FeedMessage starts 0a (field 1, length-delimited), whereas an
         API that answered 200 with an HTML or JSON error starts '<' or '{'. */
      const head = [...raw.slice(0, 16)].map((b) => b.toString(16).padStart(2, '0')).join(' ');
      return new Response(JSON.stringify({
        feedStatus: feed.status,
        feedContentType: feed.headers.get('content-type'),
        feedBytes: raw.length,
        feedWasGzipped: wasGzip,
        feedFirstBytes: head,
        feedLooksLikeText: raw.length > 0 && (raw[0] === 0x3c || raw[0] === 0x7b),
        decodedWithPosition: parsed.length,
        withRouteId: parsed.filter((v) => v.routeId).length,
        /* When route_id is mostly absent the feed is identifying trips, not
           routes, and the line has to be found some other way - so what else
           arrived matters as much as what did not. */
        withTripId: parsed.filter((v) => v.tripId).length,
        withVehicleId: parsed.filter((v) => v.vehicle && v.vehicle.id).length,
        withDirectionId: parsed.filter((v) => v.directionId !== undefined).length,
        sampleTripIds: parsed.filter((v) => v.tripId).slice(0, 6).map((v) => v.tripId),
        /* Three decoded entities as they stand, so a missing field can be
           told apart from a misparsed one. Positions are public. */
        sampleDecoded: parsed.slice(0, 3).map((v) => ({
          entityId: v.entityId ?? null, tripId: v.tripId ?? null, routeId: v.routeId ?? null,
          directionId: v.directionId ?? null, vehicle: v.vehicle ?? null,
          status: v.status ?? null, timestamp: v.timestamp ?? null,
          lat: Math.round(v.lat * 1e4) / 1e4, lon: Math.round(v.lon * 1e4) / 1e4,
          bearing: v.bearing ?? null, speed: v.speed ?? null,
        })),
        distinctRouteIds: routeIds.length,
        sampleRouteIds: routeIds.slice(0, 8),
        lineMapSize: names.size,
        sampleLineMap: [...names.entries()].slice(0, 8),
        routeIdsThatResolve: named.length,
        sampleResolved: named.slice(0, 8).map((id) => [id, names.get(id)]),
      }, null, 1), { headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS } });
    }

    const vehicles = [];
    for (const v of parsed) {
      const line = names.get(String(v.routeId)) || null;
      /* The route id carries the mode in SL's numbering only indirectly, so
         the designation decides: pendeltåg are 40-48. Without a name we
         cannot say what it is, and a board that cannot name a train should
         not draw it. */
      if (!line) continue;
      const mode = /^4[0-8]$/.test(line) ? 'TRAIN' : MODES[3];
      if (modes.size && !modes.has(mode)) continue;
      if (wanted.size && !wanted.has(line)) continue;
      if (clip && (v.lat < clip[0] || v.lat > clip[2] || v.lon < clip[1] || v.lon > clip[3])) continue;
      vehicles.push({
        id: (v.vehicle && v.vehicle.id) || v.entityId || v.tripId || null,
        line,
        routeId: v.routeId ?? null,
        tripId: v.tripId ?? null,
        directionId: v.directionId ?? null,
        lat: Math.round(v.lat * 1e6) / 1e6,
        lon: Math.round(v.lon * 1e6) / 1e6,
        bearing: typeof v.bearing === 'number' ? Math.round(v.bearing) : null,
        speed: typeof v.speed === 'number' ? Math.round(v.speed * 10) / 10 : null,
        status: v.status ?? null,
        timestamp: v.timestamp ?? null,
        mode,
      });
    }

    return new Response(JSON.stringify({ timestamp: Math.floor(Date.now() / 1000), count: vehicles.length, vehicles }), {
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        /* The browser may reuse this for the same two seconds the edge does. */
        'Cache-Control': `public, max-age=${FEED_TTL}`,
        ...CORS,
      },
    });
  },
};
