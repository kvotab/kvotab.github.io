/* ==========================================================================
   THE FULL WINDOW, FOR A TOOL PAGE

   The page without the site's header and footer, by a button with four
   corners. A page asks for it with kvot-fullwin.css and this script in its
   <head>, after the theme's boot script -- there it puts the page in the
   full window before the first paint, when it was left so -- and with a
   place for the buttons in its own bar:

       <span class="kvot-fullwin-home"></span>   (where the bar begins) the kvot mark
       <span class="kvot-fullwin"></span>        the light/dark switch and the four corners

   In the full window the kvot mark goes to the home page and the light/dark
   switch (site.js's, by kvot:toggleTheme) stands beside the button; without
   the full window they are the header's and the footer's, and hidden here.
   A page without a .kvot-fullwin-home (put before the .kvot-fullwin) has the
   mark first in .kvot-fullwin. data-parts="full" asks for the button alone,
   on a page that shows a mark and a switch of its own.

   The places are filled as the parser puts them in (a MutationObserver: its
   callback runs before the browser paints), so no frame shows the bar
   without its buttons. What is laid out from --header-height and
   --footer-height (kvot.css's .content) follows by itself, as both are 0 in
   the full window; a change fires the window's resize event, so charts and
   boxes sized from the window follow too.

   Each page is remembered on its own, in localStorage kvot.full.<page>.
   The pages that had a full window before this file have their own code.
   ========================================================================== */
(function () {
  'use strict';
  var root = document.documentElement;
  var page = (location.pathname.split('/').pop() || '').replace(/\.html?$/i, '') || 'index';
  var KEY = 'kvot.full.' + page;
  try {
    if (localStorage.getItem(KEY) === '1') root.classList.add('kvot-full');
  } catch (e) { /* storage unavailable: the page as it is */ }

  var SV = /^sv\b/i.test(root.lang || '');
  var WORDS = SV ? {
    home: 'kvot ab: startsidan',
    on: 'Hela fönstret', off: 'Lämna hela fönstret',
    onTitle: 'Hela fönstret: sidan utan webbplatsens sidhuvud och sidfot',
    offTitle: 'Visa webbplatsens sidhuvud och sidfot igen'
  } : {
    home: 'kvot ab: the home page',
    on: 'Full window', off: 'Leave the full window',
    onTitle: "Full window: the page without the site's header and footer",
    offTitle: "Show the site's header and footer again"
  };

  var MARK = '<a class="kvot-fullwin-mark kvot-fullonly" href="./index.html" title="' + WORDS.home + '">'
    + '<img src="./resources/images/kvot-logotype.svg" alt="' + WORDS.home + '" width="20" height="20"></a>';
  // four corners: out to the full window, or in again (the stylesheet shows the one that fits)
  var CORNERS = '<button type="button" class="kvot-fullbtn">'
    + '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor"'
    + ' stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    + '<path class="kvot-full-out" d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"/>'
    + '<path class="kvot-full-in" d="M6 2v4H2M10 2v4h4M14 10h-4v4M2 10h4v4"/></svg></button>';

  function isOn() {
    return root.classList.contains('kvot-full');
  }

  /** What the button says follows the window; the switch's words are site.js's. */
  function label(button) {
    var on = isOn();
    button.setAttribute('aria-pressed', String(on));
    button.setAttribute('aria-label', on ? WORDS.off : WORDS.on);
    button.title = on ? WORDS.offTitle : WORDS.onTitle;
  }

  function set(on) {
    root.classList.toggle('kvot-full', !!on);
    try { localStorage.setItem(KEY, on ? '1' : '0'); } catch (e) { /* for this visit only */ }
    var buttons = document.querySelectorAll('.kvot-fullbtn');
    for (var i = 0; i < buttons.length; i++) label(buttons[i]);
    window.dispatchEvent(new Event('resize'));
  }

  function themeSwitch() {
    // site.js's applyTheme writes the same, and keeps it so from then on
    var dark = root.getAttribute('data-theme') === 'dark';
    var words = dark ? 'Switch to light mode' : 'Switch to dark mode';
    return '<button type="button" class="theme-toggle kvot-fullonly" data-on-click="kvot:toggleTheme" title="'
      + words + '" aria-label="' + words + '">' + (dark ? '☀️' : '🌙') + '</button>';
  }

  function fill(place) {
    if (place.getAttribute('data-filled')) return;
    place.setAttribute('data-filled', '1');
    if (place.classList.contains('kvot-fullwin-home')) {
      place.innerHTML = MARK;
      return;
    }
    var parts = place.getAttribute('data-parts');
    if (parts === 'full') place.innerHTML = CORNERS;
    else place.innerHTML = (document.querySelector('.kvot-fullwin-home') ? '' : MARK) + themeSwitch() + CORNERS;
    var button = place.querySelector('.kvot-fullbtn');
    label(button);
    button.addEventListener('click', function () { set(!isOn()); });
  }

  var PLACES = '.kvot-fullwin, .kvot-fullwin-home';
  function fillAll() {
    var places = document.querySelectorAll(PLACES);
    for (var i = 0; i < places.length; i++) fill(places[i]);
  }

  var observer = new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var added = records[i].addedNodes;
      for (var j = 0; j < added.length; j++) {
        var node = added[j];
        if (node.nodeType !== 1) continue;
        if (node.matches(PLACES)) fill(node);
        else if (node.firstElementChild) {
          var inner = node.querySelectorAll(PLACES);
          for (var k = 0; k < inner.length; k++) fill(inner[k]);
        }
      }
    }
  });
  if (document.readyState === 'loading') {
    observer.observe(root, { childList: true, subtree: true });
    document.addEventListener('DOMContentLoaded', function () {
      observer.disconnect();
      fillAll();
    });
  } else {
    fillAll();
  }

  window.KvotFullWindow = { set: set, isOn: isOn, key: KEY };
})();
