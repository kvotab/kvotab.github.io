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

var latlong_init_finished = false;
var lat_dd = null;
var lat_dm = null;
var lat_dms = null;
var long_dd = null;
var long_dm = null;
var long_dms = null;
var proj_rt90 = null;
var x_rt90 = null;
var y_rt90 = null;
var proj_sweref99 = null;
var n_sweref99 = null;
var e_sweref99 = null;
// Decimal degrees. Type=float.
var latitude = null;
var longitude = null;
var url_arguments = null;

function latlong_init() {
	
	map_init();
	
	lat_dd = document.getElementById("lat_dd");
	lat_dm = document.getElementById("lat_dm");
	lat_dms = document.getElementById("lat_dms");
	long_dd = document.getElementById("long_dd");
	long_dm = document.getElementById("long_dm");
	long_dms = document.getElementById("long_dms");
	proj_rt90 = document.getElementById("proj_rt90");
	x_rt90 = document.getElementById("x_rt90");
	y_rt90 = document.getElementById("y_rt90");
	proj_sweref99 = document.getElementById("proj_sweref99");
	n_sweref99 = document.getElementById("n_sweref99");
	e_sweref99 = document.getElementById("e_sweref99");
	show_rt90_meridian(proj_rt90.value); // In map.js.
	show_sweref99_meridian(proj_sweref99.value); // In map.js.
	
	var url_args = location.search.substring(1);
	if (url_args.length > 0) {
		url_arguments = url_args 
		parse_url_arguments();
	} else {
		// Initialize panels with the default map position
		set_lat_long(59.87072523185025, 17.63431259999659);
	}
	latlong_init_finished = true;
}

function use_my_position() {
	if (!navigator.geolocation) {
		alert('Geolocation is not supported by your browser.');
		return;
	}
	navigator.geolocation.getCurrentPosition(
		function(pos) {
			set_lat_long(pos.coords.latitude, pos.coords.longitude);
			map.setView([pos.coords.latitude, pos.coords.longitude], 14);
		},
		function(err) {
			alert('Could not get your position: ' + err.message);
		},
		{ enableHighAccuracy: true, timeout: 10000 }
	);
}

// Set and get functions for external use. Storage, map, etc.
function set_lat_long(lat, lon) {
	latitude = lat;
	longitude = lon;
	update_lat();
	update_long();
	show_map_marker(lat, lon);  // In map.js.
	update_rt90();
	update_sweref99();
}
function update_set_lat_long() {
	show_map_marker(latitude, longitude);  // In map.js.
}
function get_latitude() {
	return latitude;
}
function get_longitude() {
	return longitude;
}

// Should be called when a key goes up while the field has focus.
function keyup_lat_dd(event) {
	var value = lat_dd.value;
	latitude = convert_lat_from_dd(value);
	lat_dm.value = convert_lat_to_dm(latitude);
	lat_dms.value = convert_lat_to_dms(latitude);
	update_rt90();
	update_sweref99();
	show_map_marker(latitude, longitude); // In map.js.	
}
function keyup_long_dd(event) {
	var value = long_dd.value;
	longitude = convert_long_from_dd(value);
	long_dm.value = convert_long_to_dm(longitude);
	long_dms.value = convert_long_to_dms(longitude);
	update_rt90();
	update_sweref99();
	show_map_marker(latitude, longitude); // In map.js.	
}
function keyup_lat_dm(event) {
	var value = lat_dm.value;
	latitude = convert_lat_from_dm(value);
	lat_dd.value = convert_lat_to_dd(latitude);
	lat_dms.value = convert_lat_to_dms(latitude);
	update_rt90();
	update_sweref99();
	show_map_marker(latitude, longitude); // In map.js.	
}
function keyup_long_dm(event) {
	var value = long_dm.value;
	longitude = convert_long_from_dm(value);
	long_dd.value = convert_long_to_dd(longitude);
	long_dms.value = convert_long_to_dms(longitude);
	update_rt90();
	update_sweref99();
	show_map_marker(latitude, longitude); // In map.js.	
}
function keyup_lat_dms(event) {
	var value = lat_dms.value;
	latitude = convert_lat_from_dms(value);
	lat_dd.value = convert_lat_to_dd(latitude);
	lat_dm.value = convert_lat_to_dm(latitude);
	update_rt90();
	update_sweref99();
	show_map_marker(latitude, longitude); // In map.js.	
}
function keyup_long_dms(event) {
	var value = long_dms.value;
	longitude = convert_long_from_dms(value);
	long_dd.value = convert_long_to_dd(longitude);
	long_dm.value = convert_long_to_dm(longitude);
	update_rt90();
	update_sweref99();
	show_map_marker(latitude, longitude); // In map.js.	
}
function keyup_rt90(event) {
	if ((x_rt90.value == "") || (y_rt90.value == "")) {
		latitude = null;
		longitude = null;
	} else {
		var x = parseFloat(x_rt90.value.replace(",", "."));
		var y = parseFloat(y_rt90.value.replace(",", "."));
		swedish_params(proj_rt90.value);
		var lat_lon = grid_to_geodetic(x, y);
		latitude = lat_lon[0];
		longitude = lat_lon[1];
	}
	update_lat();
	update_long();
	update_sweref99();
	show_map_marker(latitude, longitude); // In map.js.	
}
function keyup_sweref99(event) {
	if ((n_sweref99.value == "") || (e_sweref99.value == "")) {
		latitude = null;
		longitude = null;
	} else {
		var n = parseFloat(n_sweref99.value.replace(",", "."));
		var e = parseFloat(e_sweref99.value.replace(",", "."));
		swedish_params(proj_sweref99.value);
		var lat_lon = grid_to_geodetic(n, e);
		latitude = lat_lon[0];
		longitude = lat_lon[1];
	}
	update_lat();
	update_long();
	update_rt90();
	show_map_marker(latitude, longitude); // In map.js.	
}

//  Should be called when the fields loses focus.  
function blur_lat(event) {
	update_lat();
}
function blur_long(event) {
	update_long();
}
function blur_rt90(event) {
//	update_rt90();
}
function blur_sweref99(event) {
//	update_rt90();
}

// Projection changes.
function select_proj_rt90(event) {
	if (document.getElementById('rt90_show_zone').checked)
		show_rt90_meridian(proj_rt90.value);
	else
		show_rt90_meridian(null);
	update_rt90();
}
function select_proj_sweref99(event) {
	if (document.getElementById('sweref99_show_zone').checked)
		show_sweref99_meridian(proj_sweref99.value);
	else
		show_sweref99_meridian(null);
	update_sweref99();
}

// Zone overlay toggles.
function toggle_rt90_zone() {
	var on = document.getElementById('rt90_show_zone').checked;
	if (on)
		show_rt90_meridian(proj_rt90.value);
	else {
		show_rt90_meridian(null);
		document.getElementById('rt90').classList.remove('out-of-zone');
	}
	update_rt90();
}
function toggle_sweref99_zone() {
	var on = document.getElementById('sweref99_show_zone').checked;
	if (on)
		show_sweref99_meridian(proj_sweref99.value);
	else {
		show_sweref99_meridian(null);
		document.getElementById('sweref99').classList.remove('out-of-zone');
	}
	update_sweref99();
}

// Private functions.
function update_lat() {
	lat_dd.value = convert_lat_to_dd(latitude);
	lat_dm.value = convert_lat_to_dm(latitude);
	lat_dms.value = convert_lat_to_dms(latitude);
}
function update_long() {
	long_dd.value = convert_long_to_dd(longitude);
	long_dm.value = convert_long_to_dm(longitude);
	long_dms.value = convert_long_to_dms(longitude);
}
function update_rt90() {
	var card = document.getElementById('rt90');
	var showZone = document.getElementById('rt90_show_zone').checked;
	if ((latitude != null) && (longitude != null) &&
		(latitude >= -90) && (latitude <= 90) &&
		(longitude >= -180) && (longitude < 180)) {
		swedish_params(proj_rt90.value);
		var x_y = geodetic_to_grid(latitude, longitude);
		x_rt90.value = x_y[0];
		y_rt90.value = x_y[1];
		if (showZone) {
			var bounds = get_zone_bounds(proj_rt90.value);
			if (bounds && !point_in_zone_bounds(bounds, latitude, longitude))
				card.classList.add('out-of-zone');
			else
				card.classList.remove('out-of-zone');
		} else {
			card.classList.remove('out-of-zone');
		}
	} else {
		x_rt90.value = "";
		y_rt90.value = "";
		card.classList.remove('out-of-zone');
	}	
}
function update_sweref99() {
	var card = document.getElementById('sweref99');
	var showZone = document.getElementById('sweref99_show_zone').checked;
	if ((latitude != null) && (longitude != null) &&
		(latitude >= -90) && (latitude <= 90) &&
		(longitude >= -180) && (longitude < 180)) {
		swedish_params(proj_sweref99.value);
		var n_e = geodetic_to_grid(latitude, longitude);
		n_sweref99.value = n_e[0];
		e_sweref99.value = n_e[1];
		if (showZone) {
			var bounds = get_zone_bounds(proj_sweref99.value);
			if (bounds && !point_in_zone_bounds(bounds, latitude, longitude))
				card.classList.add('out-of-zone');
			else
				card.classList.remove('out-of-zone');
		} else {
			card.classList.remove('out-of-zone');
		}
	} else {
		n_sweref99.value = "";
		e_sweref99.value = "";
		card.classList.remove('out-of-zone');
	}
}

// Hide/show infotext.
function toggle_info() {
	var btn = document.getElementById("info_button");
	var ids = ["wgs84_info", "rt90_info", "sweref99_info", "map_info", "about_info"];
	var show = !btn.classList.contains("active");
	btn.classList.toggle("active", show);
	var display = show ? "block" : "none";
	for (var i = 0; i < ids.length; i++) {
		var el = document.getElementById(ids[i]);
		if (el) el.style.display = display;
	}
	setTimeout(function() { if (map) map.invalidateSize(); }, 50);
}

// Use position if url arguments are supplied.
function parse_url_arguments() {

	if (latlong_init_finished == false) {
		setTimeout(parse_url_arguments, 3000) // 3 sec.	
	}
	
	var url_args = url_arguments
	var result = url_args.split(/[=,]/);
	if ((result[0] != '') && (result[0] != null) &&
		(result[1] != '') && (result[1] != null) &&
		(result[2] != '') && (result[2] != null)) {
		if (result[0] == 'latlong') {
			set_lat_long(parseFloat(result[1]), parseFloat(result[2]));
		}
		else if (result[0] == 'rt90') {
			swedish_params(proj_rt90.value);
			var lat_lon = grid_to_geodetic(parseFloat(result[1]), 
									       parseFloat(result[2]));
			set_lat_long(lat_lon[0], lat_lon[1]);			
		}
		else if (result[0] == 'sweref99tm') {
			swedish_params(proj_sweref99.value);
			var lat_lon = grid_to_geodetic(parseFloat(result[1]), 
										   parseFloat(result[2]));
			set_lat_long(lat_lon[0], lat_lon[1]);
		}
	}
}
