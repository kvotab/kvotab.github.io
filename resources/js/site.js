/**
 * site.js - Shared components for kvot ab website
 * Generates header, navigation, footer, and map for all pages.
 */

const KVOT = (() => {
  // ── SVG Templates ──────────────────────────────────────────────────────────

  const LOGO_SVG = `
    <svg class="logo" version="1.1" xmlns="http://www.w3.org/2000/svg" viewBox="489.1 191.5 776.9 457.6" xml:space="preserve">
      <a href="./index.html" title="kvot ab">
        <path class="stTop" d="M966.1,461.6l-14.5,14.5V191.5h14.5v197.3l114.1-114.1l7,13l-71.5,72l66.8,74.2c4.8,5.5,9,9.3,12.5,11.5c3.5,2.2,7.5,3.3,11.9,3.3h2v14.5c0,0-2,0-2,0c-6.8,0-12.7-1.5-17.8-4.5c-5.1-3-10.7-8-17-15l-66.8-73.6l-39.3,39.3V461.6z"/>
        <path class="stTop" d="M1066,219.9l16,0l76.2,149.9l76.8-151.2l16,0l-87.9,173.1h-9.6L1066,219.9z"/>
        <path class="stTop" d="M1030.2,455.3c25.5,0,47.4,9.5,65.5,28.4c18.2,18.9,27.3,41.7,27.3,68.2c0,17.4-4.1,33.5-12.4,48.3c-8.3,14.8-19.5,26.4-33.8,35c-14.3,8.6-29.8,12.9-46.6,12.9s-32.3-4.3-46.6-12.9c-14.3-8.6-25.5-20.3-33.8-35c-8.3-14.8-12.4-30.9-12.4-48.3c0-26.6,9.1-49.3,27.3-68.2C982.9,464.8,1004.7,455.3,1030.2,455.3z M951.9,551.9c0,22.6,7.7,41.8,23.1,57.8c15.4,16,33.8,23.9,55.3,23.9s39.9-8,55.3-23.9c15.4-16,23.1-35.2,23.1-57.8c0-22.6-7.7-41.9-23.1-58c-15.4-16.1-33.8-24.1-55.3-24.1s-39.9,8-55.3,24.1C959.6,510,951.9,529.4,951.9,551.9z"/>
        <path class="stTop" d="M1165.8,584.2c0,10.8,3.8,20,11.5,27.6c7.7,7.6,16.9,11.5,27.7,11.5c10,0,19.3-3,27.9-9.1l8.4,11.5c-10.4,8.1-22.5,12.1-36.3,12.1c-14.8,0-27.5-5.2-38-15.6c-10.5-10.4-15.7-23-15.7-37.8V463H1123v-14.5h28.3v-42.8h14.5v42.8h71.7V463h-71.7V584.2z"/>
        <polygon class="stRight" points="889.8,230.7 624.9,383 691.3,420.7 823.7,344.6 824.4,648.1 890.7,609.6"/>
        <polygon class="stTop" points="621.9,381.4 754.6,456.8 754.8,532.7 491,380.8 820.3,191.5 886.7,229.2"/>
        <polygon class="stLeft" points="820.5,346.1 754.3,384.2 754.7,536.1 489.1,384.8 489.1,465.4 821.3,649.2"/>
      </a>
    </svg>`;

  const MARKER_SVG = `
    <svg version="1.1" xmlns="http://www.w3.org/2000/svg" viewBox="489.1 191.5 776.9 457.6" xml:space="preserve">
      <polygon class="stRight" points="889.8,230.7 624.9,383 691.3,420.7 823.7,344.6 824.4,648.1 890.7,609.6"/>
      <polygon class="stTop" points="621.9,381.4 754.6,456.8 754.8,532.7 491,380.8 820.3,191.5 886.7,229.2"/>
      <polygon class="stLeft" points="820.5,346.1 754.3,384.2 754.7,536.1 489.1,384.8 489.1,465.4 821.3,649.2"/>
    </svg>`;

  const ICON_ADDRESS = '<path d="M 15.212,16.424c 2.874,0, 5.212-2.338, 5.212-5.212C 20.424,8.338, 18.086,6, 15.212,6S 10,8.338, 10,11.212 C 10,14.086, 12.338,16.424, 15.212,16.424z M 15.212,8c 1.77,0, 3.212,1.44, 3.212,3.212s-1.44,3.212-3.212,3.212S 12,12.982, 12,11.212 S 13.44,8, 15.212,8zM 14.484,31.458c 0.168,0.186, 0.33,0.306, 0.486,0.39c 0.002,0.002, 0.006,0.002, 0.008,0.004 c 0.108,0.056, 0.214,0.098, 0.314,0.098c 0.1,0, 0.206-0.042, 0.314-0.098c 0.002-0.002, 0.006-0.002, 0.008-0.004 c 0.156-0.084, 0.318-0.204, 0.486-0.39c0,0, 9.296-10.11, 10.23-18.87c 0.056-0.452, 0.094-0.91, 0.094-1.376 C 26.424,5.020, 21.404,0, 15.212,0S 4,5.020, 4,11.212c0,0.474, 0.038,0.936, 0.096,1.394C 5.054,21.362, 14.484,31.458, 14.484,31.458z M 15.212,2 c 5.080,0, 9.212,4.132, 9.212,9.212c0,0.338-0.024,0.698-0.082,1.164c-0.716,6.712-7.018,14.588-9.048,16.984 c-2.082-2.4-8.474-10.256-9.214-17C 6.026,11.918, 6,11.554, 6,11.212C 6,6.132, 10.132,2, 15.212,2z"/>';
  const ICON_PHONE = '<path d="M164.9 24.6c-7.7-18.6-28-28.5-47.4-23.2l-88 24C12.1 30.2 0 46 0 64C0 311.4 200.6 512 448 512c18 0 33.8-12.1 38.6-29.5l24-88c5.3-19.4-4.6-39.7-23.2-47.4l-96-40c-16.3-6.8-35.2-2.1-46.3 11.6L304.7 368C234.3 334.7 177.3 277.7 144 207.3L193.3 167c13.7-11.2 18.4-30 11.6-46.3l-40-96z"/>';
  const ICON_MAIL = '<path d="M48 64C21.5 64 0 85.5 0 112c0 15.1 7.1 29.3 19.2 38.4L236.8 313.6c11.4 8.5 27 8.5 38.4 0L492.8 150.4c12.1-9.1 19.2-23.3 19.2-38.4c0-26.5-21.5-48-48-48H48zM0 176V384c0 35.3 28.7 64 64 64H448c35.3 0 64-28.7 64-64V176L294.4 339.2c-22.8 17.1-54 17.1-76.8 0L0 176z"/>';
  const ICON_LINKEDIN = '<path d="M100.28 448H7.4V148.9h92.88zM53.79 108.1C24.09 108.1 0 83.5 0 53.8a53.79 53.79 0 0 1 107.58 0c0 29.7-24.1 54.3-53.79 54.3zM447.9 448h-92.68V302.4c0-34.7-.7-79.2-48.29-79.2-48.29 0-55.69 37.7-55.69 76.7V448h-92.78V148.9h89.08v40.8h1.3c12.4-23.5 42.69-48.3 87.88-48.3 94 0 111.28 61.9 111.28 142.3V448z"/>';
  const ICON_MATLAB = '<path d="M4.323 16.248C3.13 15.354 1.64 14.31 0 13.118l5.814-2.236 2.385 1.789c-1.789 2.087-2.981 2.832-3.876 3.578zm15.95-6.26c-.447-1.193-.745-2.385-1.193-3.578-.447-1.342-.894-2.534-1.64-3.578-.298-.447-.894-1.491-1.64-1.491-.149 0-.298.149-.447.149-.447.149-1.043 1.043-1.193 1.64-.447.745-1.342 1.938-1.938 2.683-.149.298-.447.596-.596.745-.447.298-.894.745-1.491 1.043-.149 0-.298.149-.447.149-.447 0-.745.298-1.043.447-.447.447-.894 1.043-1.342 1.491 0 .149-.149.298-.298.447l2.236 1.64c1.64-1.938 3.578-3.876 4.919-7.602 0 0-.447 4.025-4.025 8.348-2.236 2.534-4.025 3.876-4.323 4.174 0 0 .596-.149 1.193.149 1.193.447 1.789 2.087 2.236 3.279.298.894.745 1.64 1.043 2.534 1.193-.298 1.938-.745 2.683-1.491s1.491-1.64 2.236-2.385c1.342-1.64 2.981-3.727 5.068-2.683.298.149.745.447.894.596.447.298.745.596 1.193 1.043.745.596 1.043 1.043 1.64 1.342-1.491-2.981-2.534-5.963-3.727-9.093z"/>';
  const ICON_GITHUB = '<path fill-rule="evenodd" clip-rule="evenodd" d="M48.854 0C21.839 0 0 22 0 49.217c0 21.756 13.993 40.172 33.405 46.69 2.427.49 3.316-1.059 3.316-2.362 0-1.141-.08-5.052-.08-9.127-13.59 2.934-16.42-5.867-16.42-5.867-2.184-5.704-5.42-7.17-5.42-7.17-4.448-3.015.324-3.015.324-3.015 4.934.326 7.523 5.052 7.523 5.052 4.367 7.496 11.404 5.378 14.235 4.074.404-3.178 1.699-5.378 3.074-6.6-10.839-1.141-22.243-5.378-22.243-24.283 0-5.378 1.94-9.778 5.014-13.2-.485-1.222-2.184-6.275.486-13.038 0 0 4.125-1.304 13.426 5.052a46.97 46.97 0 0 1 12.214-1.63c4.125 0 8.33.571 12.213 1.63 9.302-6.356 13.427-5.052 13.427-5.052 2.67 6.763.97 11.816.485 13.038 3.155 3.422 5.015 7.822 5.015 13.2 0 18.905-11.404 23.06-22.324 24.283 1.78 1.548 3.316 4.481 3.316 9.126 0 6.6-.08 11.897-.08 13.526 0 1.304.89 2.853 3.316 2.364 19.412-6.52 33.405-24.935 33.405-46.691C97.707 22 75.788 0 48.854 0z"/>';
  const ICON_ORGNR = '<path d="M661 84v860H84V84h577m29.3-80H54.7C26.7 4 4 30.9 4 64v900c0 33.1 22.7 60 50.7 60h635.6c28 0 50.7-26.9 50.7-60V64c0-33.1-22.7-60-50.7-60z"/> <path d="M505 742v201H240V742h265m61-80H178.1c-16.8 0-18.1 9.5-18.1 21.2v318.5c0 11.7 1.4 21.2 18.1 21.2H566c16.8 0 19-9.5 19-21.2V683.2c0-11.7-2.2-21.2-19-21.2z m376-267v548H742.1V395H942m63.9-80H677.5c-14.2 0-15.3 18.6-15.3 41.6v624.7c0 23 1.1 41.6 15.3 41.6h328.4c14.2 0 16.1-18.6 16.1-41.6V356.6c0-23-1.9-41.6-16.1-41.6zM291 223H185c-22.1 0-40-17.9-40-40s17.9-40 40-40h106c22.1 0 40 17.9 40 40s-17.9 40-40 40z m270 0H455c-22.1 0-40-17.9-40-40s17.9-40 40-40h106c22.1 0 40 17.9 40 40s-17.9 40-40 40zM291 380H185c-22.1 0-40-17.9-40-40s17.9-40 40-40h106c22.1 0 40 17.9 40 40s-17.9 40-40 40z m270 0H455c-22.1 0-40-17.9-40-40s17.9-40 40-40h106c22.1 0 40 17.9 40 40s-17.9 40-40 40zM291 537H185c-22.1 0-40-17.9-40-40s17.9-40 40-40h106c22.1 0 40 17.9 40 40s-17.9 40-40 40z m270 0H455c-22.1 0-40-17.9-40-40s17.9-40 40-40h106c22.1 0 40 17.9 40 40s-17.9 40-40 40z"/> <path d="M766 557h-39.7c-22.1 0-40-17.9-40-40s17.9-40 40-40H766c22.1 0 40 17.9 40 40s-17.9 40-40 40z m0 179h-43c-22.1 0-40-17.9-40-40s17.9-40 40-40h43c22.1 0 40 17.9 40 40s-17.9 40-40 40z m0 179h-36.4c-22.1 0-40-17.9-40-40s17.9-40 40-40H766c22.1 0 40 17.9 40 40s-17.9 40-40 40z"/>';
  const ICON_VAT = '<path d="M122.88,58.58l-35,52.92L60,93.6l1.85-3.91,20.43,13,.25.17a4.15,4.15,0,0,0,5.73-1.32l1.13-1.8.06,0,5.27-8.57,24-35.3,4.21,2.69ZM33.15,39.26H24.2L17.65,15.32h7.51l.67,4L28.6,32.64h.45l3.4-12.92.7-4.4h7.26L33.15,39.26Zm28.1,0H53.74l-.67-3.95,0-.12-3.63-.07-3,.15-.63,4H38.49l7.26-23.94h9l6.55,23.94Zm-9.32-9.47L50.3,22h-.45l-2.07,7.84,2.07,0,2.08,0ZM78.69,15.84l-.4,5.4L73.4,21H73l-.19,10.47.3,7.77h-7.4l.37-7L65.85,21h-.48l-4.92.22L60,20.72l.41-5.4H78.29l.4.52ZM48.59,83.28,48,82.72l-8.3,8.53a2.09,2.09,0,0,1-.14.17,2.51,2.51,0,0,1-3.55,0l-8.7-8.7-9,8.54h0a2.51,2.51,0,0,1-3.5-.05L6.3,82.59l-1.78,2A2.51,2.51,0,0,1,0,83.15V2.51A2.51,2.51,0,0,1,2.51,0H93.87a2.5,2.5,0,0,1,2.5,2.51V21.69l-1.23-.79a4.72,4.72,0,0,0-3.78-.6V5H5v71.7a2.5,2.5,0,0,1,2.8.32.8.8,0,0,1,.13.13H8L16.66,86l9-8.53a2.49,2.49,0,0,1,3.49,0h0l8.63,8.63,8.35-8.6a2.49,2.49,0,0,1,3.49-.1h0l1.58,1.46-2,2.94a4.74,4.74,0,0,0-.63,1.49Zm11.56-18h-41a1.85,1.85,0,0,1,0-3.7H62.59l-2.44,3.7ZM68.29,53H18.59a1.85,1.85,0,1,1,0-3.7H70.73L68.29,53Zm51.31-5.84L84.6,100,56.68,82.14l35-52.92,27.91,17.9ZM94.08,61.57a7.54,7.54,0,1,1-10.3-2.77,7.53,7.53,0,0,1,10.3,2.77Zm15.52-8.2L86.13,88.29a4.91,4.91,0,0,0-6.77,1.49l-11-7.07a4.9,4.9,0,0,0-1.49-6.77L90.31,41a4.89,4.89,0,0,0,6.76-1.48l11.05,7.07a4.9,4.9,0,0,0,1.48,6.77Z"/>';

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
    if (!header) return;
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
    if (!header) return;

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
        <li><a href="./index.html#links">links</a></li>
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
    if (!footer) return;

    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const themeIcon = currentTheme === 'dark' ? '☀️' : '🌙';
    const themeTitle = currentTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';

    footer.innerHTML = `
    <div class="footer-content">
      <span class="footer-center">
        kvot ab |
        <button type="button" class="icon-btn" onclick="KVOT.toggleMap()" aria-label="Show or hide the office map">
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
      <button class="theme-toggle" onclick="KVOT.toggleTheme()" title="${themeTitle}">${themeIcon}</button>
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
