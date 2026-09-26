/**
 * What to say when the editor does not start.
 *
 * A classic script, not a module, and deliberately: it has to run even when
 * module loading is the thing that failed, which is the failure it exists to
 * explain. Nothing here imports anything, and it must stay that way.
 *
 * In a file rather than inline in index.html for two reasons. The page carries
 * a Content Security Policy, and an inline script is the thing a policy exists
 * to refuse -- `'unsafe-inline'` would have bought this one script at the cost
 * of allowing every other. And it was the one place in the application that
 * built markup from a string: `p.innerHTML = body`, with bodies assembled by
 * hand out of `<p>` and `<pre>`. Safe, because every character of it was
 * written here -- but the rule is that elements are built, not parsed, and a
 * rule with an exception in it is not checkable. It is elements now, and
 * `test/lint.js` reads this file along with the rest.
 */

(function () {
	var box = document.getElementById('boot-problem');

	/** A tag with text and child nodes, since there is no `el()` down here. */
	function node(tag, ...kids) {
		var e = document.createElement(tag);
		for (var i = 0; i < kids.length; i++) {
			var k = kids[i];
			if (k == null) continue;
			e.appendChild(typeof k === 'string' ? document.createTextNode(k) : k);
		}
		return e;
	}
	function link(href, text) {
		var a = node('a', text);
		a.href = href;
		return a;
	}

	function show(title, blocks) {
		box.replaceChildren();
		box.appendChild(node('h1', title));
		var body = node('div');
		for (var i = 0; i < blocks.length; i++) {
			if (blocks[i]) body.appendChild(blocks[i]);
		}
		box.appendChild(body);
		box.hidden = false;
		document.getElementById('app').hidden = true;
	}

	if (location.protocol === 'file:') {
		// The app is ES modules, and a browser refuses to load those from a
		// file:// page (its origin is opaque). Nothing here will work until it
		// is served over HTTP.
		var path = decodeURIComponent(location.pathname).replace(/\/index\.html$/, '');
		show('This page needs to be served, not opened', [
			node('p', 'You have opened ', node('code', 'index.html'),
				' straight from disk. Browsers block JavaScript modules on ',
				node('code', 'file://'),
				' pages, so the editor cannot start — which is why the buttons '
				+ 'do nothing.'),
			node('p', 'Start the server in the project folder:'),
			node('pre', 'cd ' + path + '\npython3 serve.py 8080'),
			node('p', 'then open ', link('http://localhost:8080/', 'http://localhost:8080/'),
				'. This tool is arbitrary.'),
			node('p', 'Use ', node('code', 'serve.py'), ' rather than ',
				node('code', 'python3 -m http.server'),
				'. The stdlib server sends no cache headers, so browsers hold on to '
				+ 'JavaScript modules they already have — and because each module '
				+ 'is cached separately, an edited file can meet an old one and the two '
				+ 'disagree about what the program does. ',
				node('code', 'serve.py'), ' sends ', node('code', 'no-store'),
				', so a plain refresh always picks up your edits.'),
		]);
		return;
	}

	// Served over HTTP but the module never signalled success: report it rather
	// than leave a page of dead buttons.
	var started = false;
	var moduleError = null;
	var shown = false;
	// Four seconds is a guess about a machine, and a slow one -- a cold cache,
	// a busy disk, a laptop on battery -- can take longer to load the modules
	// and still start. The message then took the page away for good, leaving
	// a working editor hidden behind "did not start". So a start that comes
	// late takes the message down again.
	window.__ecolegoStarted = function () {
		started = true;
		if (!shown) return;
		box.hidden = true;
		box.replaceChildren();
		document.getElementById('app').hidden = false;
	};

	// A module that fails to link reports itself here, message and all. The
	// commonest cause by far is a *stale* module: browsers cache JavaScript
	// modules aggressively, and a Worker keeps its own cache on top of the
	// page's, so an edited file can meet an old one and the two disagree about
	// what is exported. That has a specific fix, so it gets a specific
	// message rather than "the editor did not start".
	window.addEventListener('error', function (e) {
		if (!moduleError && e && e.message) moduleError = e.message;
	});

	function looksStale(message) {
		return /does not provide an export named|Cannot find module|Failed to fetch dynamically|error loading dynamically imported module/i
			.test(message || '');
	}

	setTimeout(function () {
		if (started) return;
		shown = true;
		var detail = moduleError
			? [node('p', 'The browser reported:'), node('pre', moduleError)]
			: [];

		if (looksStale(moduleError)) {
			show('The browser is mixing old and new code', detail.concat([
				node('p', 'One file was reloaded and another was served from the cache, '
					+ 'so they disagree about what the first one exports. Nothing is '
					+ 'wrong with the files on disk.'),
				node('p', node('b', 'Reload ignoring the cache'), ' — ',
					node('kbd', '⌘⇧R'), ' on a Mac, ',
					node('kbd', 'Ctrl⇧R'), ' elsewhere — and it will go away.'),
				node('p', 'If it comes back, the pages are being served by something '
					+ 'that allows caching. Use the server in this folder, which '
					+ 'disables it:'),
				node('pre', 'python3 serve.py 8080'),
			]));
			return;
		}

		show('The editor did not start', detail.concat([
			node('p', 'The page loaded but its JavaScript did not. Open the browser '
				+ 'console (', node('kbd', 'F12'), ') for the underlying error.'),
			node('p', 'The usual causes are a server that does not send ',
				node('code', 'text/javascript'), ' for ', node('code', '.js'),
				' files, or a missing file under ', node('code', 'src/'), '.'),
		]));
	}, 4000);
}());
