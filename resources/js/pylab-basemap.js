/* PyLAB: the basemaps of geographic axes (geobasemap, the axes' Basemap).
 *
 * Nothing is fetched until axes have a basemap; then only what their view
 * needs. Most basemaps are web map tiles (Web Mercator), drawn into the axes'
 * longitude-latitude box a strip of rows at a time, as one picture, so a
 * saved figure has it too. streets-light and streets-dark are OpenStreetMap's
 * tiles toned here. darkwater, grayland and bluegreen are Natural Earth's
 * land and lakes, drawn in two colours. Each map's attribution is drawn in
 * the corner of the axes.
 *
 * The renderer (pylab-figure.js) calls draw(ctx, ax, fr, renderer); what is
 * still loading goes into renderer.waits, and renderer.onTile is called as it
 * arrives.
 */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});

  const OSM = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const OSM_NOTE = '© OpenStreetMap contributors';
  const GIBS = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/';
  const GIBS_NOTE = 'Imagery: NASA GIBS (ESDIS)';
  const NE = 'https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@v5.1.2/geojson/';
  const NE_NOTE = 'Made with Natural Earth';
  const MAPS = {
    streets: { url: OSM, max: 19, note: OSM_NOTE },
    'streets-light': { url: OSM, max: 19, note: OSM_NOTE, tone: 'light' },
    'streets-dark': { url: OSM, max: 19, note: OSM_NOTE, tone: 'dark' },
    topographic: { url: 'https://tile.opentopomap.org/{z}/{x}/{y}.png', max: 17,
      note: 'Map data © OpenStreetMap contributors, SRTM | Map style © OpenTopoMap (CC-BY-SA)' },
    satellite: { url: 'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg', max: 15,
      note: 'EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2016)' },
    colorterrain: { url: `${GIBS}ASTER_GDEM_Color_Shaded_Relief/default/GoogleMapsCompatible_Level12/{z}/{y}/{x}.jpg`, max: 12,
      note: `${GIBS_NOTE}, ASTER GDEM` },
    grayterrain: { url: `${GIBS}ASTER_GDEM_Greyscale_Shaded_Relief/default/GoogleMapsCompatible_Level12/{z}/{y}/{x}.jpg`, max: 12,
      note: `${GIBS_NOTE}, ASTER GDEM` },
    landcover: { url: `${GIBS}MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual/default/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png`, max: 8,
      note: `${GIBS_NOTE}, MODIS land cover` },
    darkwater: { land: '#e6e6e1', water: '#4b5661', note: NE_NOTE },
    grayland: { land: '#c2c2c2', water: '#ffffff', note: NE_NOTE },
    bluegreen: { land: '#b3d09c', water: '#9fc5e8', note: NE_NOTE },
  };
  const MAX_TILES_IN_VIEW = 64;
  const MAX_KEPT = 600;
  const MAXLAT = 85.0511287798066;

  let generation = 0;               // counts arrivals, so that a picture made before one is made again
  const tiles = new Map();          // url (and tone) -> { state, src, promise, cbs }
  const layers = new Map();         // Natural Earth file -> { state, polys, promise, cbs }
  const pictures = new Map();       // a view's key -> its finished picture

  /* Web Mercator: a latitude's place down the world's square (0 at the top), and back. */
  const mercY = (lat) => { const s = Math.sin(lat * Math.PI / 180); return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI); };
  const latOf = (y) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180 / Math.PI;

  function settle(entry) {
    generation++;
    for (const cb of entry.cbs) { try { cb(); } catch (e) { console.error(e); } }
    entry.cbs.clear();
  }

  /* OpenStreetMap's tiles in greys, light or dark (water kept apart by its blue). */
  function toned(img, tone) {
    const c = document.createElement('canvas');
    c.width = img.naturalWidth || img.width;
    c.height = img.naturalHeight || img.height;
    const g = c.getContext('2d');
    g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height);
    const p = d.data;
    for (let i = 0; i < p.length; i += 4) {
      const r = p[i], gr = p[i + 1], b = p[i + 2];
      const y = 0.299 * r + 0.587 * gr + 0.114 * b;
      const water = b - r > 30 && b > 150;
      let v, w;
      if (tone === 'light') { v = 255 - (255 - y) * 0.5; w = [214, 224, 230]; }
      else { v = 30 + (255 - y) * 0.62; w = [17, 22, 28]; }
      if (water) { p[i] = w[0]; p[i + 1] = w[1]; p[i + 2] = w[2]; }
      else p[i] = p[i + 1] = p[i + 2] = v;
    }
    g.putImageData(d, 0, 0);
    return c;
  }

  /* A tile, from the cache or asked for now (with CORS, so that the figure can be saved). */
  function tile(url, tone, onLoad) {
    const key = tone ? `${url}#${tone}` : url;
    let t = tiles.get(key);
    if (t && t.state === 'failed' && Date.now() - t.when > 60000) { tiles.delete(key); t = null; }   // asked for again after a minute
    if (t) {
      tiles.delete(key);
      tiles.set(key, t);
    } else {
      t = { state: 'loading', src: null, cbs: new Set() };
      t.promise = new Promise((resolve) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.decoding = 'async';
        img.onload = () => {
          try { t.src = tone ? toned(img, tone) : img; t.state = 'ok'; } catch (e) { t.state = 'failed'; t.when = Date.now(); }
          settle(t); resolve();
        };
        img.onerror = () => { t.state = 'failed'; t.when = Date.now(); settle(t); resolve(); };
        img.src = url;
      });
      tiles.set(key, t);
      while (tiles.size > MAX_KEPT) tiles.delete(tiles.keys().next().value);
    }
    if (t.state === 'loading' && onLoad) t.cbs.add(onLoad);
    return t;
  }

  /* A Natural Earth layer's polygons: rings as flat [lon, lat, ...] arrays, with their box. */
  function layer(file, onLoad) {
    let L = layers.get(file);
    if (!L) {
      L = { state: 'loading', polys: null, cbs: new Set() };
      L.promise = fetch(`${NE}${file}.geojson`)
        .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then((doc) => { L.polys = polygons(doc); L.state = 'ok'; }, () => { L.state = 'failed'; })
        .then(() => settle(L));
      layers.set(file, L);
    }
    if (L.state === 'loading' && onLoad) L.cbs.add(onLoad);
    return L;
  }

  function polygons(doc) {
    const out = [];
    for (const f of doc.features || []) {
      const g = f.geometry;
      if (!g) continue;
      const polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
      for (const poly of polys) {
        const box = [Infinity, Infinity, -Infinity, -Infinity];
        const rings = poly.filter((ring) => ring.length > 2).map((ring) => {
          const a = new Float64Array(ring.length * 2);
          ring.forEach(([x, y], i) => {
            a[2 * i] = x; a[2 * i + 1] = y;
            if (x < box[0]) box[0] = x; if (y < box[1]) box[1] = y;
            if (x > box[2]) box[2] = x; if (y > box[3]) box[3] = y;
          });
          return a;
        });
        if (rings.length) out.push({ rings, box });
      }
    }
    return out;
  }

  /* The view's longitudes and latitudes (latitudes as far as the tiles go). */
  function view(fr) {
    const xa = Math.min(fr.xl[0], fr.xl[1]), xb = Math.max(fr.xl[0], fr.xl[1]);
    const ya = Math.min(fr.yl[0], fr.yl[1]), yb = Math.max(fr.yl[0], fr.yl[1]);
    return { xa, xb, ya, yb };
  }

  /* darkwater, grayland, bluegreen: water, then land, then lakes, with copies
     of the world 360° apart where the view goes past ±180°. */
  function drawLand(ctx, fr, spec, renderer) {
    const r = fr.r;
    const { xa, xb, ya, yb } = view(fr);
    const fine = xb - xa < 90;
    const parts = [[layer(fine ? 'ne_50m_land' : 'ne_110m_land', renderer.onTile), spec.land],
      [layer(fine ? 'ne_50m_lakes' : 'ne_110m_lakes', renderer.onTile), spec.water]];
    ctx.save();
    ctx.beginPath();
    ctx.rect(r.x, r.y, r.w, r.h);
    ctx.clip();
    ctx.fillStyle = spec.water;
    ctx.fillRect(r.x, r.y, r.w, r.h);
    let failed = false;
    for (const [L, colour] of parts) {
      if (L.state === 'loading') { renderer.waits.push(L.promise); continue; }
      if (L.state !== 'ok') { failed = true; continue; }
      ctx.fillStyle = colour;
      ctx.beginPath();
      for (let k = Math.floor((xa + 180) / 360); k <= Math.floor((xb + 180) / 360); k++) {
        const off = 360 * k;
        for (const p of L.polys) {
          if (p.box[2] + off < xa || p.box[0] + off > xb || p.box[3] < ya || p.box[1] > yb) continue;
          for (const ring of p.rings) {
            ctx.moveTo(fr.fx(ring[0] + off), fr.fy(ring[1]));
            for (let i = 2; i < ring.length; i += 2) ctx.lineTo(fr.fx(ring[i] + off), fr.fy(ring[i + 1]));
            ctx.closePath();
          }
        }
      }
      ctx.fill('evenodd');
    }
    ctx.restore();
    return failed ? `${spec.note} (the land could not be loaded)` : spec.note;
  }

  /* Tiles: the zoom level whose pixels are about the screen's, the tiles over
     the view (at most 64), drawn into a picture of the axes' box. */
  function drawTiles(ctx, fr, spec, renderer) {
    const r = fr.r;
    const s = Math.max(1, Math.min(2, Math.abs(ctx.getTransform().a) || 1));
    const { xa, xb } = view(fr);
    let { ya, yb } = view(fr);
    ya = Math.max(ya, -MAXLAT); yb = Math.min(yb, MAXLAT);
    if (!(xb > xa) || !(yb > ya) || r.w < 2 || r.h < 2) return spec.note;
    const ppd = r.w * s / (xb - xa);
    let z = Math.max(0, Math.min(spec.max ?? 18, Math.round(Math.log2(ppd * 360 / 256))));
    let n, i0, i1, j0, j1;
    for (;; z--) {
      n = 2 ** z;
      i0 = Math.floor((xa + 180) / 360 * n); i1 = Math.ceil((xb + 180) / 360 * n) - 1;
      j0 = Math.max(0, Math.floor(mercY(yb) * n)); j1 = Math.min(n - 1, Math.ceil(mercY(ya) * n) - 1);
      if ((i1 - i0 + 1) * (j1 - j0 + 1) <= MAX_TILES_IN_VIEW || z === 0) break;
    }
    const W = Math.max(1, Math.round(r.w * s)), H = Math.max(1, Math.round(r.h * s));
    const key = [spec.url, spec.tone, z, fr.xl, fr.yl, W, H, r.w, r.h].join('|');
    let pic = pictures.get(key);
    let failed = 0, total = 0;
    if (!pic) {
      pic = document.createElement('canvas');
      pic.width = W; pic.height = H;
      const g = pic.getContext('2d');
      g.imageSmoothingEnabled = true;
      let pending = false;
      const strips = z < 3 ? 64 : z < 6 ? 16 : 4;
      for (let i = i0; i <= i1; i++) {
        const lonA = i / n * 360 - 180, lonB = (i + 1) / n * 360 - 180;
        const X0 = Math.floor((fr.fx(lonA) - r.x) * s), X1 = Math.ceil((fr.fx(lonB) - r.x) * s);
        for (let j = j0; j <= j1; j++) {
          total++;
          const url = spec.url.replace('{z}', z).replace('{x}', ((i % n) + n) % n).replace('{y}', j);
          const t = tile(url, spec.tone, renderer.onTile);
          if (t.state === 'loading') { renderer.waits.push(t.promise); pending = true; continue; }
          if (t.state !== 'ok') { failed++; continue; }
          const src = t.src, tw = src.naturalWidth || src.width, th = src.naturalHeight || src.height;
          for (let k = 0; k < strips; k++) {
            const Y0 = Math.floor((fr.fy(latOf((j + k / strips) / n)) - r.y) * s);
            const Y1 = Math.ceil((fr.fy(latOf((j + (k + 1) / strips) / n)) - r.y) * s);
            if (Y1 <= 0 || Y0 >= H || Y1 <= Y0) continue;
            g.drawImage(src, 0, k * th / strips, tw, th / strips, X0, Y0, X1 - X0, Y1 - Y0);
          }
        }
      }
      if (!pending && !failed) {
        pictures.set(key, pic);
        while (pictures.size > 8) pictures.delete(pictures.keys().next().value);
      }
    }
    ctx.drawImage(pic, r.x, r.y, r.w, r.h);
    if (total && failed === total) return `${spec.note} (the map tiles could not be loaded)`;
    return spec.note;
  }

  PL.basemap = {
    names: Object.keys(MAPS),
    /* The basemap of geographic axes, in their box; returns its attribution. */
    draw(ctx, ax, fr, renderer) {
      const spec = ax.basemapCustom || MAPS[ax.basemap];
      if (!spec) return null;
      return spec.url ? drawTiles(ctx, fr, spec, renderer) : drawLand(ctx, fr, spec, renderer);
    },
    get generation() { return generation; },
  };
})(window);
