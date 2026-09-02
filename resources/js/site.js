/**
 * site.js - Shared components for kvot ab website
 * Generates header, navigation, footer, and map for all pages.
 */

const KVOT = (() => {
  // ── Icons ──────────────────────────────────────────────────────────────────
  // Path data lives in kvot-icons.js; see the note there.

  if (typeof KVOT_ICONS === 'undefined') {
    /* A bare destructuring TypeError here would say nothing about the cause. */
    reportFailure('site.js', new Error('kvot-icons.js must load before site.js'), {
      userMessage: 'The page could not draw its header and footer.'
    });
  }
  const { LOGO_SVG, MARKER_SVG, ICON_ADDRESS, ICON_PHONE, ICON_MAIL,
          ICON_LINKEDIN, ICON_MATLAB, ICON_GITHUB, ICON_ORGNR, ICON_VAT } =
    (typeof KVOT_ICONS === 'undefined' ? {} : KVOT_ICONS);

  // ── All projects ───────────────────────────────────────────────────────────

  const ALL_PROJECTS = [
    {
      href: './rdc.html',
      label: 'Radionuclide Decay Chains',
      desc: 'Explore the ICRP Publication 107 decay data as an interactive chain graph, and plot activity over time.',
    },
    {
      href: './rb.html',
      label: 'HDF5 Browser',
      desc: 'Open .h5 files straight in the browser — walk the tree, inspect datasets, plot them and export to Excel.',
    },
    {
      href: './logn.html',
      label: 'Lognormal Conversions',
      desc: 'Convert between lognormal parameterisations — μ and σ, geometric mean and GSD, percentiles — with the equations shown.',
    },
    {
      href: './proj.html',
      label: 'Swedish Coordinate Conversions',
      desc: 'Convert between WGS 84, SWEREF 99 and RT 90, one point at a time or in bulk from a pasted list.',
    },
    {
      href: './skbref.html',
      label: 'SKB Reference Checker',
      desc: 'Check citations and reference lists in a Word document against the SKB reference guides.',
    },
    {
      href: './skb_qa_summary.html',
      label: 'SKB QA Summary',
      desc: 'Summarise QA review status across Excel workbooks, with filters, statistics and CSV export.',
    },
  ];

  // ── Map tile configuration (single source of truth; also used by map.js) ────

  const TILE_ACCESS_TOKEN = 'ENe8N6YxrncW4x3EDSJgqDZUylzlnpOMk4WCgzYhdm0sAP6l0dr6BlQaijzEznsa';
  const TILE_URL = `https://tile.jawg.io/jawg-light/{z}/{x}/{y}.png?access-token=${TILE_ACCESS_TOKEN}`;
  const TILE_ATTRIBUTION =
    '<a href="https://www.jawg.io" title="Tiles Courtesy of Jawg Maps" target="_blank" rel="noopener noreferrer">&copy; <b>Jawg</b>Maps</a>' +
    ' | <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">&copy; OSM contributors</a>';
  const TILE_MAX_ZOOM = 22;

  // Leaflet is only needed when a map is actually revealed, so it is fetched
  // on demand rather than blocking every page load. Hashes pin the CDN copy.
  const LEAFLET_CSS = {
    href: 'https://unpkg.com/leaflet@1.9.2/dist/leaflet.css',
    integrity: 'sha384-kxXhFDZB0L84bBV/apPOb8zGC+fsQ1dBPpKXPUXc1zRymi4BaueVyC27iDDPdssp',
  };
  const LEAFLET_JS = {
    src: 'https://unpkg.com/leaflet@1.9.2/dist/leaflet.js',
    integrity: 'sha384-zrFQ4BIvCMUhUb6NKv9N6+lGhC7+M9l7lyLfVaa/dqQtK4PLTS6LZNvAyPJvls7U',
  };

  // ── Helper: create an SVG icon ─────────────────────────────────────────────

  function svgIcon(viewBox, pathD, opts = {}) {
    const cls = opts.class || 'smallsvg';
    const title = opts.title || '';
    const extra = opts.extra || '';
    return `<svg class="${cls}" xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" ${extra}><title>${title}</title>${pathD}</svg>`;
  }

  // ── Theme Management ───────────────────────────────────────────────────────

  const THEME_KEY = 'kvot-theme';

  // localStorage throws in some privacy modes and under file:// — never let
  // that take the rest of the page down with it.
  function storedTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }

  function rememberTheme(theme) {
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
  }

  function systemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function getPreferredTheme() {
    return storedTheme() || systemTheme();
  }

  // Apply a theme without recording it as a deliberate choice. Persisting here
  // would turn the very first page view into an explicit preference and cut the
  // site off from later system theme changes.
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelectorAll('.theme-toggle').forEach(btn => {
      btn.textContent = theme === 'dark' ? '☀️' : '🌙';
      btn.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
      btn.setAttribute('aria-label', btn.title);
    });
    // notify listeners that theme changed
    document.documentElement.dispatchEvent(new CustomEvent('kvot-theme-change',{detail:{theme}}));
  }

  // Apply *and* remember — for an explicit choice by the visitor.
  function setTheme(theme) {
    applyTheme(theme);
    rememberTheme(theme);
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    setTheme(current === 'dark' ? 'light' : 'dark');
  }

  // Apply theme immediately on load (before render). The inline boot snippet in
  // each page's <head> has usually done this already; this keeps pages without
  // it correct.
  applyTheme(getPreferredTheme());

  // Follow the system while the visitor has not chosen for themselves.
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    if (!storedTheme()) applyTheme(e.matches ? 'dark' : 'light');
  });

  // ── Header ─────────────────────────────────────────────────────────────────

  function renderHeader(title, extraHTML = '') {
    const header = document.querySelector('header');
    if (!header) {
      /* Silently returning here used to make the whole site chrome vanish on a
         page that had forgotten its <header> element, with no clue why. */
      reportFailure('KVOT.renderHeader', new Error('No <header> element on this page'));
      return;
    }
    // A page with a title gets it as its <h1>; pages that supply their own
    // heading in the content (the landing page) pass an empty title.
    const heading = title
      ? `<h1 class="title">${title}</h1>`
      : '<section class="title"></section>';
    header.innerHTML = LOGO_SVG + heading + extraHTML + '<section></section>';
  }

  // ── Navigation toggle + overlay ────────────────────────────────────────────

  function renderNav(currentPage) {
    const header = document.querySelector('header');
    if (!header) {
      reportFailure('KVOT.renderNav', new Error('No <header> element to anchor the navigation to'));
      return;
    }

    // Hamburger toggle. A real <button> so it is focusable, operable with
    // Enter/Space and announced with its expanded state.
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'nav-toggle';
    toggle.setAttribute('aria-label', 'Toggle navigation');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', 'menu');
    toggle.innerHTML = '<span class="bar-top"></span><span class="bar-mid"></span><span class="bar-bot"></span>';
    header.insertAdjacentElement('afterend', toggle);

    // Build project sub-links (exclude current page)
    const projectLinks = ALL_PROJECTS
      .filter(p => p.href !== './' + currentPage)
      .map(p => `<li class="nav-sub"><a href="${p.href}">${p.label}</a></li>`)
      .join('\n        ');

    // Dropdown card
    const menu = document.createElement('div');
    menu.id = 'menu';
    menu.innerHTML = `
      <ul>
        <li><a href="./index.html">home</a></li>
        <li><div class="nav-divider"></div></li>
        <li><div class="nav-section-label">projects</div></li>
        ${projectLinks}
      </ul>`;
    toggle.insertAdjacentElement('afterend', menu);

    function setMenuOpen(open) {
      toggle.classList.toggle('opened', open);
      menu.classList.toggle('open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function closeMenu() {
      setMenuOpen(false);
    }

    // Toggle handler
    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      setMenuOpen(!menu.classList.contains('open'));
    });

    // Close when clicking a link
    menu.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMenu));

    // Close when clicking anywhere outside
    document.addEventListener('click', function (e) {
      if (!menu.contains(e.target) && !toggle.contains(e.target)) {
        closeMenu();
      }
    });

    // Close on Escape key, returning focus to the control that opened it
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || !menu.classList.contains('open')) return;
      closeMenu();
      toggle.focus();
    });
  }

  // ── Footer ─────────────────────────────────────────────────────────────────

  function renderFooter(extraIcons = '') {
    const footer = document.querySelector('footer');
    if (!footer) {
      reportFailure('KVOT.renderFooter', new Error('No <footer> element on this page'));
      return;
    }

    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const themeIcon = currentTheme === 'dark' ? '☀️' : '🌙';
    const themeTitle = currentTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';

    footer.innerHTML = `
    <div class="footer-content">
      <span class="footer-center">
        kvot ab |
        <button type="button" class="icon-btn" data-action="kvot:toggleMap" aria-label="Show or hide the office map">
          ${svgIcon('0 0 32 32', ICON_ADDRESS, { title: 'address' })}
        </button>
        valhallagatan 16 &bull; 753 34 &bull; uppsala |
        <a href="tel:0733822313">${svgIcon('0 0 512 512', ICON_PHONE, { title: 'phone' })}</a>
        <a href="mailto:pa@kvotab.se">${svgIcon('0 0 512 512', ICON_MAIL, { title: 'mail' })}</a>
        <a href="https://linkedin.com/in/per-anders-ekstrom" target="_blank" rel="noopener noreferrer">${svgIcon('0 0 448 512', ICON_LINKEDIN, { title: 'linkedin' })}</a>
        <a href="https://www.mathworks.com/matlabcentral/profile/authors/718179" target="_blank" rel="noopener noreferrer">${svgIcon('0 0 24 24', ICON_MATLAB, { title: 'matlab' })}</a>
        <a href="https://github.com/kvotab" target="_blank" rel="noopener noreferrer">${svgIcon('0 0 98 96', ICON_GITHUB, { title: 'github' })}</a>
        ${extraIcons}
      </span>
      <button class="theme-toggle" data-action="kvot:toggleTheme" title="${themeTitle}">${themeIcon}</button>
    </div>`;
  }

  // ── Leaflet Map ────────────────────────────────────────────────────────────

  const OFFICE_COORDS = [59.87072523185025, 17.63431259999659];

  let leafletPromise = null;
  let registeredMapId = 'kvotmap';
  const mapInstances = {};

  // Fetch Leaflet the first time a map is actually needed.
  function loadLeaflet() {
    if (typeof L !== 'undefined') return Promise.resolve(L);
    if (leafletPromise) return leafletPromise;

    leafletPromise = new Promise((resolve, reject) => {
      if (!document.querySelector(`link[href="${LEAFLET_CSS.href}"]`)) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = LEAFLET_CSS.href;
        link.integrity = LEAFLET_CSS.integrity;
        link.crossOrigin = 'anonymous';
        document.head.appendChild(link);
      }
      const script = document.createElement('script');
      script.src = LEAFLET_JS.src;
      script.integrity = LEAFLET_JS.integrity;
      script.crossOrigin = 'anonymous';
      script.onload = () => resolve(L);
      script.onerror = () => {
        leafletPromise = null;
        reject(new Error('Leaflet could not be loaded'));
      };
      document.head.appendChild(script);
    });
    return leafletPromise;
  }

  // Register the office map container. The map itself is built on first reveal,
  // so pages that are never asked for it pay nothing.
  function initMap(elementId) {
    const id = elementId || registeredMapId;
    const el = document.getElementById(id);
    if (!el) return null;
    registeredMapId = id;
    el.style.visibility = 'hidden';
    return null;
  }

  function buildMap(el) {
    if (mapInstances[el.id]) return mapInstances[el.id];

    const svgMarker = L.divIcon({
      html: MARKER_SVG,
      className: '',
      iconSize: [70, 70],
      iconAnchor: [25, 5],
    });

    const map = L.map(el).setView(OFFICE_COORDS, 14);
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: TILE_MAX_ZOOM }).addTo(map);
    L.marker(OFFICE_COORDS, { icon: svgMarker, title: 'kvot ab, valhallagatan 16, uppsala' }).addTo(map);

    mapInstances[el.id] = map;
    return map;
  }

  function toggleMap(elementId) {
    const el = document.getElementById(elementId || registeredMapId);
    if (!el) return;

    const showing = el.style.visibility === 'hidden' || !el.style.visibility;
    el.style.visibility = showing ? 'visible' : 'hidden';
    if (!showing) return;

    loadLeaflet().then(() => {
      // The container was hidden while Leaflet sized itself; make it re-measure.
      buildMap(el).invalidateSize();
    }).catch(() => {
      el.style.visibility = 'hidden';
      el.textContent = '';
    });
  }

  // ── Project cards ──────────────────────────────────────────────────────────

  function renderProjectCards(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.innerHTML = ALL_PROJECTS.map(p => `
      <a class="project-card" href="${p.href}">
        <span class="project-card-title">${p.label}</span>
        <span class="project-card-desc">${p.desc}</span>
      </a>`).join('');
  }

  // ── Actions declared by the chrome this module renders ────────────────────
  /*
    Namespaced so a page cannot collide with them. Registered once, at load,
    against the shared dispatcher in kvot-actions.js.
  */
  if (typeof registerActions === 'function') {
    registerActions({
      'kvot:toggleTheme': () => toggleTheme(),
      'kvot:toggleMap': () => toggleMap(),
    });
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  return {
    renderHeader,
    renderNav,
    renderFooter,
    renderProjectCards,
    initMap,
    toggleMap,
    toggleTheme,
    svgIcon,
    ICON_ADDRESS,
    ICON_PHONE,
    ICON_MAIL,
    ICON_ORGNR,
    ICON_VAT,
    PROJECTS: ALL_PROJECTS,
    TILE_URL,
    TILE_ATTRIBUTION,
    TILE_MAX_ZOOM,
  };
})();
