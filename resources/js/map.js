// Author: Arnold Andreasson, info@mellifica.se
// Copyright (c) 2007-2016 Arnold Andreasson 
// License: MIT License as follows:
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

var map;
var markers;

// Simplified Sweden outline (~45 points, clockwise from southern tip)
var sweden_outline = [
	[55.34,12.95],[55.38,13.80],[55.72,14.20],[56.05,14.58],[56.16,15.62],
	[56.27,16.40],[56.67,16.37],[57.10,16.82],[57.72,16.70],[58.35,16.83],
	[58.75,17.95],[59.33,18.07],[59.85,18.93],[60.12,18.55],[60.63,17.92],
	[61.20,17.15],[61.73,17.12],[62.30,17.38],[62.63,17.94],[63.27,18.72],
	[63.60,19.85],[63.83,20.26],[64.40,21.00],[64.75,21.07],[65.30,21.55],
	[65.58,22.15],[65.84,24.15],[66.38,23.64],[67.17,23.67],[67.87,20.90],
	[68.42,21.46],[68.58,20.04],[69.06,18.51],[69.06,18.00],[68.45,16.00],
	[68.35,15.30],[67.37,15.50],[66.60,14.46],[66.13,14.80],[65.00,13.70],
	[64.00,13.40],[63.10,12.10],[62.07,12.30],[61.05,12.51],[60.15,12.44],
	[59.08,11.85],[58.88,11.18],[58.33,11.38],[57.52,11.76],[57.05,12.35],
	[56.52,12.56],[56.10,12.65],[55.34,12.95]
];

function map_init() {
	const accessToken = 'ENe8N6YxrncW4x3EDSJgqDZUylzlnpOMk4WCgzYhdm0sAP6l0dr6BlQaijzEznsa';
	const styleId = 'jawg-light';
	map = L.map('coord-map', { attributionControl: false, zoomControl: false }).setView([59.87072523185025, 17.63431259999659], 14);
	var streetLayer = L.tileLayer(
		`https://tile.jawg.io/${styleId}/{z}/{x}/{y}.png?access-token=${accessToken}`, {
		maxZoom: 22
	});
	var satelliteLayer = L.tileLayer(
		'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
		maxZoom: 19,
		attribution: '&copy; Esri'
	});
	streetLayer.addTo(map);
	map._baseLayers = { street: streetLayer, satellite: satelliteLayer };
	map._activeBase = 'street';
	map.on('baselayerchange', function(e) {
		if (e.layer.options.maxZoom && map.getZoom() > e.layer.options.maxZoom)
			map.setZoom(e.layer.options.maxZoom);
	});

	markers = L.marker([59.87072523185025, 17.63431259999659]);
	markers.addTo(map);

	map.on('click', function(e) {
		set_lat_long(e.latlng.lat, e.latlng.lng);
	});
}

function map_zoom_in() { map.zoomIn(); }
function map_zoom_out() { map.zoomOut(); }
function map_toggle_layer() {
	var bl = map._baseLayers;
	var btn = document.getElementById('map_layer_btn');
	if (map._activeBase === 'street') {
		map.removeLayer(bl.street);
		bl.satellite.addTo(map);
		map._activeBase = 'satellite';
		if (map.getZoom() > bl.satellite.options.maxZoom)
			map.setZoom(bl.satellite.options.maxZoom);
		if (btn) btn.innerHTML = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="12" y1="3" x2="12" y2="21"/></svg> Map';
	} else {
		map.removeLayer(bl.satellite);
		bl.street.addTo(map);
		map._activeBase = 'street';
		if (btn) btn.innerHTML = '<svg class=\"btn-icon\" viewBox=\"0 0 24 24\"><circle cx=\"12\" cy=\"12\" r=\"10\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\"/><ellipse cx=\"12\" cy=\"12\" rx=\"4.5\" ry=\"10\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.2\"/><line x1=\"2\" y1=\"12\" x2=\"22\" y2=\"12\" stroke=\"currentColor\" stroke-width=\"1.2\"/><line x1=\"3.5\" y1=\"7.5\" x2=\"20.5\" y2=\"7.5\" stroke=\"currentColor\" stroke-width=\"0.8\"/><line x1=\"3.5\" y1=\"16.5\" x2=\"20.5\" y2=\"16.5\" stroke=\"currentColor\" stroke-width=\"0.8\"/></svg> Satellite';
	}
}

function show_map_marker(lat, lon) {
	if (lat == null || lon == null || isNaN(lat) || isNaN(lon)) {
		markers.remove();
		return;
	}
	var ll = L.latLng(lat, lon);
	map.panTo(ll);
	markers.setLatLng(ll);
	if (!map.hasLayer(markers)) markers.addTo(map);
}

// ── Bulk conversion markers ────────────────────────────────────────
var bulk_markers_layer = null;

// Returns {west, east} longitude bounds for a projection zone, or null for wgs84_dd
function get_zone_bounds(proj) {
	if (proj === 'wgs84_dd') return null;
	var z = rt90_zones[proj];
	if (z) {
		var half = 1.125;
		if (proj === 'rt90_2.5_gon_v') return { west: 10.7, east: 24.45 };
		if (proj === 'rt90_5.0_gon_o') return { west: z.cm_grs - half, east: 24.35 };
		return { west: z.cm_grs - half, east: z.cm_grs + half };
	}
	z = sweref99_zones[proj];
	if (z) {
		if (z.national) return { west: 10.8, east: 24.35 };
		// For local zones with polygon data, use polygon test
		if (typeof sweref99_zone_polygons !== 'undefined' && sweref99_zone_polygons[proj])
			return { polygon: true, key: proj };
		var w = z.cm - 0.75, e = z.cm + 0.75;
		if (proj === 'sweref_99_1200') w = z.cm - 1.10;
		if (proj === 'sweref_99_2315') e = 24.25;
		return { west: w, east: e };
	}
	return null;
}

// Point-in-polygon test (ray casting) for SWEREF 99 zone polygons
function point_in_zone_bounds(bounds, lat, lon) {
	if (!bounds) return true;
	if (bounds.polygon) {
		var rings = sweref99_zone_polygons[bounds.key];
		if (!rings) return true;
		for (var r = 0; r < rings.length; r++) {
			if (point_in_ring(rings[r], lat, lon)) return true;
		}
		return false;
	}
	return lon >= bounds.west && lon <= bounds.east;
}

// Ray-casting point-in-polygon for a single ring of [lat, lng] points
function point_in_ring(ring, lat, lon) {
	var inside = false;
	for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
		var yi = ring[i][0], xi = ring[i][1];
		var yj = ring[j][0], xj = ring[j][1];
		if (((yi > lat) !== (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi))
			inside = !inside;
	}
	return inside;
}

function show_bulk_markers(latLonArray, outOfZone, inputRows, outputRows) {
	clear_bulk_markers();
	if (!latLonArray || latLonArray.length === 0) return;
	bulk_markers_layer = L.featureGroup();
	var bounds = [];
	latLonArray.forEach(function(pt, i) {
		var bad = outOfZone && outOfZone[i];
		var num = i + 1;
		var sz = num < 100 ? 20 : (num < 1000 ? 24 : 28);
		var icon = L.divIcon({
			className: bad ? 'bulk-pin bulk-pin-bad' : 'bulk-pin',
			html: '<span>' + num + '</span>',
			iconSize: [sz, sz],
			iconAnchor: [sz / 2, sz / 2]
		});
		var m = L.marker([pt[0], pt[1]], { icon: icon });
		// Hover tooltip with coordinates
		var tip = '<b>#' + num + '</b>';
		tip += '<br>Lat: ' + pt[0].toFixed(6) + '&deg;  Lon: ' + pt[1].toFixed(6) + '&deg;';
		if (inputRows && inputRows[i]) tip += '<br>In: ' + inputRows[i];
		if (outputRows && outputRows[i]) tip += '<br>Out: ' + outputRows[i];
		m.bindTooltip(tip, { direction: 'top', offset: [0, -sz / 2] });
		m.addTo(bulk_markers_layer);
		bounds.push([pt[0], pt[1]]);
	});
	bulk_markers_layer.addTo(map);
	if (bounds.length > 1) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
	else if (bounds.length === 1) { map.setView(bounds[0], 12); }
}
function clear_bulk_markers() {
	if (bulk_markers_layer) { map.removeLayer(bulk_markers_layer); bulk_markers_layer = null; }
}

// ── RT 90 zone parameters (Lantmäteriet official) ──────────────────
// GRS80 central meridians (used for the conversion), Bessel meridians shown in info
var rt90_zones = {
	"rt90_7.5_gon_v": { cm_grs: 11.0+18.375/60, cm_bessel: 11+18/60+29.8/3600, name: "RT90 7.5 gon V", gon: "7,5 gon V", scale_grs: 1.000006 },
	"rt90_5.0_gon_v": { cm_grs: 13.0+33.376/60, cm_bessel: 13+33/60+29.8/3600, name: "RT90 5 gon V",   gon: "5 gon V",   scale_grs: 1.0000058 },
	"rt90_2.5_gon_v": { cm_grs: 15.0+48/60+22.624306/3600, cm_bessel: 15+48/60+29.8/3600, name: "RT90 2.5 gon V", gon: "2,5 gon V", scale_grs: 1.00000561024 },
	"rt90_0.0_gon_v": { cm_grs: 18.0+3.378/60, cm_bessel: 18+3/60+29.8/3600, name: "RT90 0 gon",      gon: "0 gon",     scale_grs: 1.0000054 },
	"rt90_2.5_gon_o": { cm_grs: 20.0+18.379/60, cm_bessel: 20+18/60+29.8/3600, name: "RT90 2.5 gon O", gon: "2,5 gon O", scale_grs: 1.0000052 },
	"rt90_5.0_gon_o": { cm_grs: 22.0+33.380/60, cm_bessel: 22+33/60+29.8/3600, name: "RT90 5 gon O",   gon: "5 gon O",   scale_grs: 1.0000049 }
};

// SWEREF 99 zone parameters (Lantmäteriet official)
var sweref99_zones = {
	"sweref_99_tm":   { cm: 15.00, scale: 0.9996, fe: 500000, name: "SWEREF 99 TM", national: true },
	"sweref_99_1200": { cm: 12.00, scale: 1, fe: 150000, name: "SWEREF 99 12 00" },
	"sweref_99_1330": { cm: 13.50, scale: 1, fe: 150000, name: "SWEREF 99 13 30" },
	"sweref_99_1500": { cm: 15.00, scale: 1, fe: 150000, name: "SWEREF 99 15 00" },
	"sweref_99_1630": { cm: 16.50, scale: 1, fe: 150000, name: "SWEREF 99 16 30" },
	"sweref_99_1800": { cm: 18.00, scale: 1, fe: 150000, name: "SWEREF 99 18 00" },
	"sweref_99_1415": { cm: 14.25, scale: 1, fe: 150000, name: "SWEREF 99 14 15" },
	"sweref_99_1545": { cm: 15.75, scale: 1, fe: 150000, name: "SWEREF 99 15 45" },
	"sweref_99_1715": { cm: 17.25, scale: 1, fe: 150000, name: "SWEREF 99 17 15" },
	"sweref_99_1845": { cm: 18.75, scale: 1, fe: 150000, name: "SWEREF 99 18 45" },
	"sweref_99_2015": { cm: 20.25, scale: 1, fe: 150000, name: "SWEREF 99 20 15" },
	"sweref_99_2145": { cm: 21.75, scale: 1, fe: 150000, name: "SWEREF 99 21 45" },
	"sweref_99_2315": { cm: 23.25, scale: 1, fe: 150000, name: "SWEREF 99 23 15" }
};

// ── Build clipped zone polygon (Sutherland-Hodgman) ────────────────
// Clips the Sweden outline to a vertical strip [west, east].
// Preserves vertex order so concave shapes render correctly.
function clip_zone_to_sweden(west, east) {
	// Clip polygon against a single vertical line.
	// keep = 'right' keeps points with lon >= x; 'left' keeps lon <= x.
	function clip_edge(poly, x, keep) {
		var out = [];
		var n = poly.length;
		for (var i = 0; i < n; i++) {
			var cur = poly[i];
			var nxt = poly[(i + 1) % n];
			var cur_in = keep === 'right' ? cur[1] >= x : cur[1] <= x;
			var nxt_in = keep === 'right' ? nxt[1] >= x : nxt[1] <= x;
			if (cur_in) out.push(cur);
			if (cur_in !== nxt_in) {
				var t = (x - cur[1]) / (nxt[1] - cur[1]);
				out.push([cur[0] + t * (nxt[0] - cur[0]), x]);
			}
		}
		return out;
	}
	var poly = sweden_outline.slice(); // don't mutate original
	poly = clip_edge(poly, west, 'right'); // keep lon >= west
	poly = clip_edge(poly, east, 'left');  // keep lon <= east
	return poly.length >= 3 ? poly : null;
}

// Clip a detailed sweden_border ring to a longitude strip [west, east]
function clip_zone_to_sweden_ring(ring, west, east) {
	function clip_edge(poly, x, keep) {
		var out = [];
		var n = poly.length;
		for (var i = 0; i < n; i++) {
			var cur = poly[i];
			var nxt = poly[(i + 1) % n];
			var cur_in = keep === 'right' ? cur[1] >= x : cur[1] <= x;
			var nxt_in = keep === 'right' ? nxt[1] >= x : nxt[1] <= x;
			if (cur_in) out.push(cur);
			if (cur_in !== nxt_in) {
				var t = (x - cur[1]) / (nxt[1] - cur[1]);
				out.push([cur[0] + t * (nxt[0] - cur[0]), x]);
			}
		}
		return out;
	}
	var poly = ring.slice();
	poly = clip_edge(poly, west, 'right');
	poly = clip_edge(poly, east, 'left');
	return poly.length >= 3 ? poly : null;
}

// Format decimal degrees as D°MM'SS.S"
function fmt_dms(deg) {
	var d = Math.floor(deg);
	var m = Math.floor((deg - d) * 60);
	var s = ((deg - d) * 60 - m) * 60;
	return d + '\u00b0' + (m < 10 ? '0' : '') + m + '\u2032' + s.toFixed(1) + '\u2033';
}

// ── RT 90 zone overlay ─────────────────────────────────────────────
var rt90_zone_layer = null;
function show_rt90_meridian(projection) {
	if (rt90_zone_layer) { map.removeLayer(rt90_zone_layer); rt90_zone_layer = null; }
	var z = rt90_zones[projection];
	if (!z) return;

	var half_width = 1.125; // 2.5 gon ≈ 2.25° → half = 1.125°
	var west, east;
	if (projection === "rt90_2.5_gon_v") {
		// National zone covers all of Sweden
		west = 10.7; east = 24.45;
	} else if (projection === "rt90_5.0_gon_o") {
		west = z.cm_grs - half_width; east = 24.35;
	} else {
		west = z.cm_grs - half_width; east = z.cm_grs + half_width;
	}

	var group = L.featureGroup();

	var popupContent =
		'<b>' + z.name + '</b>' +
		(projection === "rt90_2.5_gon_v" ? ' (national)' : '') +
		'<br>Central meridian (Bessel): ' + fmt_dms(z.cm_bessel) + 'E' +
		'<br>Ellipsoid: Bessel 1841' +
		'<br>a = 6\u2009377\u2009397.155 m' +
		'<br>1/f = 299.1528128' +
		'<br>Scale: 1.0' +
		'<br>False easting: 1\u2009500\u2009000 m' +
		'<hr style="margin:4px 0"><i style="font-size:0.85em">GRS 80 approximation<br>' +
		'Central meridian: ' + fmt_dms(z.cm_grs) + 'E' +
		'<br>Scale: ' + z.scale_grs + '</i>';

	if (projection === "rt90_2.5_gon_v" && typeof sweden_border !== 'undefined') {
		// National zone: use detailed Sweden border
		for (var r = 0; r < sweden_border.length; r++) {
			var border = sweden_border[r].concat([sweden_border[r][0]]);
			L.polyline(border, { color: '#b8860b', weight: 3 }).bindPopup(popupContent).addTo(group);
		}
	} else if (typeof sweden_border !== 'undefined') {
		// Local zone: clip each sweden_border ring to the zone strip
		for (var r = 0; r < sweden_border.length; r++) {
			var clipped = clip_zone_to_sweden_ring(sweden_border[r], west, east);
			if (clipped) {
				var ring = clipped.concat([clipped[0]]);
				L.polyline(ring, {
					color: '#b8860b', weight: 3, dashArray: '6,4'
				}).bindPopup(popupContent).addTo(group);
			}
		}
	} else {
		var poly = clip_zone_to_sweden(west, east);
		if (poly) {
			var ring = poly.concat([poly[0]]);
			L.polyline(ring, {
				color: '#b8860b', weight: 3, dashArray: '6,4'
			}).bindPopup(popupContent).addTo(group);
		}
	}

	// Central meridian line
	L.polyline([[55.0, z.cm_grs], [69.1, z.cm_grs]], {
		color: '#8B6914', weight: 1.5, dashArray: '4,6', opacity: 0.7
	}).addTo(group);

	rt90_zone_layer = group;
	group.addTo(map);
}

// ── SWEREF 99 zone overlay ─────────────────────────────────────────
var sweref99_zone_layer = null;
function show_sweref99_meridian(projection) {
	if (sweref99_zone_layer) { map.removeLayer(sweref99_zone_layer); sweref99_zone_layer = null; }
	var z = sweref99_zones[projection];
	if (!z) return;

	var group = L.featureGroup();

	var popupContent =
		'<b>' + z.name + '</b>' +
		(z.national ? ' (national)' : '') +
		'<br>Central meridian: ' + fmt_dms(z.cm) + 'E' +
		'<br>Ellipsoid: GRS 80' +
		'<br>a = 6\u2009378\u2009137 m' +
		'<br>1/f = 298.257222101' +
		'<br>Scale factor: ' + z.scale +
		'<br>False northing: 0 m' +
		'<br>False easting: ' + z.fe.toLocaleString('en') + ' m';

	if (z.national && typeof sweden_border !== 'undefined') {
		// National zone: use detailed Sweden border
		for (var r = 0; r < sweden_border.length; r++) {
			var border = sweden_border[r].concat([sweden_border[r][0]]);
			L.polyline(border, { color: '#cc3333', weight: 3 }).bindPopup(popupContent).addTo(group);
		}
	} else if (typeof sweref99_zone_polygons !== 'undefined' && sweref99_zone_polygons[projection]) {
		// Local zone: use actual municipality-based boundary polygons
		var rings = sweref99_zone_polygons[projection];
		// Draw interactive borders for each ring
		for (var r = 0; r < rings.length; r++) {
			var border = rings[r].concat([rings[r][0]]);
			L.polyline(border, {
				color: '#cc3333', weight: 3, dashArray: '6,4'
			}).bindPopup(popupContent).addTo(group);
		}
	} else {
		// Fallback: simple longitude strip
		var west = z.cm - 0.75, east = z.cm + 0.75;
		if (projection === "sweref_99_1200") west = z.cm - 1.10;
		if (projection === "sweref_99_2315") east = 24.25;
		var poly = clip_zone_to_sweden(west, east);
		if (poly) {
			var ring = poly.concat([poly[0]]);
			L.polyline(ring, {
				color: '#cc3333', weight: 3, dashArray: '6,4'
			}).bindPopup(popupContent).addTo(group);
		}
	}

	// Central meridian line
	L.polyline([[55.0, z.cm], [69.1, z.cm]], {
		color: '#991111', weight: 1.5, dashArray: '4,6', opacity: 0.7
	}).addTo(group);

	sweref99_zone_layer = group;
	group.addTo(map);
}
