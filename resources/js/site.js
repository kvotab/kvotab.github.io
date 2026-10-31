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

  /*
    The menu and the landing page list the projects under these headings, in
    this order, and each project names its own. Within a heading the projects
    keep their order in ALL_PROJECTS. A project naming a heading that is not
    here is listed under "Other" at the end rather than left out.
  */
  const PROJECT_GROUPS = [
    { id: 'data', label: 'Data and statistics' },
    { id: 'nuclear', label: 'Nuclear data and dose' },
    { id: 'models', label: 'Modelling' },
    { id: 'documents', label: 'Reports and references' },
    { id: 'accounts', label: 'Accounts and tax' },
    { id: 'everyday', label: 'Everyday' },
  ];

  const ALL_PROJECTS = [
    {
      href: './rb.html',
      label: 'HDF5 Browser',
      group: 'data',
      desc: 'Open .h5 files straight in the browser — walk the tree, inspect datasets, plot them and export to Excel.',
    },
    {
      href: './ensdf.html',
      label: 'Chart of Nuclides',
      group: 'nuclear',
      desc: 'Every nuclide in the Evaluated Nuclear Structure Data File by N and Z, coloured by half-life or decay mode, with its states, Q-values, levels and radiation, and the whole decay chain of any radionuclide.',
    },
    {
      href: './distributions.html',
      label: 'Probability Distributions',
      group: 'data',
      desc: 'Define and compare probability distributions — 38 parametric families in several parameterisations each, empirical distributions from data, truncation — with their statistics, seeded samples (random, Latin hypercube, Sobol, Halton), fits to data by maximum likelihood or moments ranked by AIC and goodness of fit, and calculations from tail probabilities to Monte Carlo sums.',
    },
    {
      href: './kompartment.html',
      label: 'Kompartment',
      group: 'models',
      desc: 'Build compartment models in the browser — blocks and fluxes drawn on a canvas, expressions, uncertainty and calibration — and solve them with a choice of stiff and non-stiff solvers.',
    },
    {
      href: './smui.html',
      label: 'User Interface for statsmodels',
      group: 'data',
      desc: 'A statistics workbench in the working style of JMP, computed by statsmodels in the browser: a data table with modeling types and row states, Distribution, Bivariate Analysis, Fit Model, multivariate methods, time series, survival, quality and design of experiments, and Graph Maker, with linked graphs and the Python behind every result.',
    },
    {
      href: './rtm.html',
      label: 'Reactive Transport',
      group: 'models',
      desc: 'Specify and solve reactive transport models: reactions written the usual way, a batch reactor or a column with diffusion and advection, and an analytic sparse Jacobian built from your own reaction set.',
    },
    {
      href: './skbref.html',
      label: 'SKB Reference Checker',
      group: 'documents',
      desc: 'Check citations and reference lists in a Word document against the SKB reference guides.',
    },
    {
      href: './zoterify.html',
      label: 'Zoterify',
      group: 'documents',
      desc: 'Turn the plain-text citations in a Word document into live Zotero citations, matched against your own zotero.sqlite, with every change tracked in your own document.',
    },
    {
      href: './skb_qa_summary.html',
      label: 'SKB QC Summary',
      group: 'documents',
      desc: 'Summarise QA review status across Excel workbooks, with filters, statistics and CSV export.',
    },
    {
      href: './dose_coefficients.html',
      label: 'Dose Coefficients',
      group: 'nuclear',
      desc: 'Committed effective and equivalent dose coefficients for members of the public, by age at intake, for ingestion and inhalation, calculated with the ICRP’s own models in the ICRP 60 system (Publication 72) or the ICRP 103 system (Publication 158): retention, excretion and the models themselves.',
    },
    {
      href: './proj.html',
      label: 'Swedish Coordinate Conversions',
      group: 'data',
      desc: 'Convert between WGS 84, SWEREF 99 and RT 90, one point at a time or in bulk from a pasted list.',
    },
    {
      href: './FARF31.html',
      label: 'FARF31 Far-Field Transport',
      group: 'models',
      desc: 'SKB’s far-field model FARF31: radionuclides along a stream tube with dispersion, matrix diffusion and sorption, and decay chains of any length, solved in the Laplace domain from the release you give; FARF31’s own input and output files read and written.',
    },
    {
      href: './facsimile.html',
      label: 'Canister Radiolysis',
      group: 'models',
      desc: 'Solve the FACSIMILE radiolysis and corrosion model of the gas in an intact spent-fuel canister, with editable reactions and a sparse analytic Jacobian.',
    },
    {
      href: './erosion_corrosion.html',
      label: 'Erosion and Corrosion',
      group: 'models',
      desc: 'SKB’s buffer erosion and canister corrosion calculation for every deposition hole of a KBS-3 layout, from hydro data you drop in: rejection criteria, time to advection, sulphide-driven failure times and the key outputs of the PSAR workbook.',
    },
    {
      href: './SimpleFunctions.html',
      label: 'Simple Functions',
      group: 'models',
      desc: 'Radionuclide solubility limits by SKB’s Simple Functions: the SR-Site and PSAR calculation for 20 elements in the water of a failed canister, Monte Carlo over groundwater compositions and equilibrium constants, with controlling solids, speciation and sensitivities.',
    },
    {
      href: './rdc.html',
      label: 'Radionuclide Decay Chains',
      group: 'nuclear',
      desc: 'Explore the ICRP Publication 107 decay data as an interactive chain graph, and plot activity over time.',
    },
    {
      href: './logn.html',
      label: 'Lognormal Conversions',
      group: 'data',
      desc: 'Convert between lognormal parameterisations — μ and σ, geometric mean and GSD, percentiles — with the equations shown.',
    },
    {
      href: './arsredovisning.html',
      label: 'Digital årsredovisning',
      group: 'accounts',
      desc: 'Build a K2 annual report from a SIE file and check the iXBRL against what Bolagsverket looks at.',
    },
    {
      href: './inkomstdeklaration.html',
      label: 'Inkomstdeklaration',
      group: 'accounts',
      desc: 'Build the SRU files for Skatteverket from a SIE file, using BAS official account mapping.',
    },
    {
      href: './flashcards.html',
      label: 'Glosor',
      group: 'everyday',
      desc: 'Practise English and Spanish vocabulary on cards, in Swedish: themes from colours and animals to irregular verbs, both ways round, the words read out, and word lists of one’s own from school, typed or read off a photo of the sheet, that can be shared as a link.',
    },
    {
      href: './winnetkakort.html',
      label: 'Winnetkakort',
      group: 'everyday',
      desc: 'Practise the arithmetic facts with Winnetka cards, in Swedish: the task on the front, the answer on the back, and one pile for what you know and one for what needs more practice — addition and subtraction, the times tables, division, fractions, percent and negative numbers.',
    },
    {
      href: './gitarr.html',
      label: 'Gitarrstämmare',
      group: 'everyday',
      desc: 'Tune an acoustic guitar to standard tuning with the microphone, in Swedish: the page hears which string is played and shows on a picture of the headstock which key to turn, and which way, until the string is in tune.',
    },
    {
      href: './svensk_text.html',
      label: 'Svensk text',
      group: 'everyday',
      desc: 'Translate English subtitles into Swedish in the browser, for free, with Google’s translator built into Chrome: whole sentences go to the translator rather than single subtitles, fillers and sound descriptions are left out, and every subtitle is checked against Swedish subtitling limits — two lines, 42 characters to a line, 17 characters a second.',
    },
    {
      href: './uppsala.html',
      label: 'Uppsala → Solna',
      group: 'everyday',
      desc: 'Live departures for the next SL commuter trains from Uppsala C towards Solna, refreshed every 30 seconds.',
    },
    {
      href: './solna.html',
      label: 'Solna → Uppsala',
      group: 'everyday',
      desc: 'Live departures for the next SL commuter trains from Solna to Uppsala C, refreshed every 30 seconds.',
    },
  ];

  // ── Map tile configuration (single source of truth; also used by map.js) ────

  const TILE_ACCESS_TOKEN = 'ENe8N6YxrncW4x3EDSJgqDZUylzlnpOMk4WCgzYhdm0sAP6l0dr6BlQaijzEznsa';
  // Jawg publishes the same cartography light and dark, so the basemap can
  // follow the site's theme without any label or line moving on the switch.
  const TILE_STYLES = { light: 'jawg-light', dark: 'jawg-dark' };
  function tileUrl(theme) {
    const style = TILE_STYLES[theme] || TILE_STYLES.light;
    return `https://tile.jawg.io/${style}/{z}/{x}/{y}.png?access-token=${TILE_ACCESS_TOKEN}`;
  }
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

  // A page may pin the theme it falls back to when the visitor has not chosen
  // one, by putting data-theme-default on <html>. uppsala.html and solna.html
  // do it on a phone: there the board fills the screen and the site chrome is
  // hidden, toggle and all, so a dark system setting produced a dark board
  // with no way to change it. A theme the visitor has actually chosen still
  // wins over this — it is a default, not an override.
  function pageDefaultTheme() {
    const pinned = document.documentElement.getAttribute('data-theme-default');
    return pinned === 'light' || pinned === 'dark' ? pinned : null;
  }

  function systemTheme() {
    return pageDefaultTheme()
      || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
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

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }

  function toggleTheme() {
    setTheme(currentTheme() === 'dark' ? 'light' : 'dark');
  }

  // Apply theme immediately on load (before render). The inline boot snippet in
  // each page's <head> has usually done this already; this keeps pages without
  // it correct.
  applyTheme(getPreferredTheme());

  // Follow the system while the visitor has not chosen for themselves.
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    // Back through getPreferredTheme, so a page that has pinned a default is
    // not dragged off it the moment the system flips.
    if (!storedTheme()) applyTheme(getPreferredTheme());
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

  // ── Navigation toggle + menu ───────────────────────────────────────────────
  /*
    The hamburger opens every project under its heading. As a single list it
    had grown taller than a laptop's screen, and the menu, being fixed, could
    not be scrolled: the last projects were out of reach. The headings now sit
    side by side where there is room, the panel scrolls inside itself where
    there is not (a phone, a short window), and a field at the top narrows the
    list as one types.

    #menu covers the window below the header and dims the page; a click there
    closes the menu without reaching the page underneath. It and the toggle
    stay children of <body>, because several pages' full-window modes hide
    them as `body > .nav-toggle` and `body > #menu`. It is a div with a role
    rather than a <nav>, since rdc.css styles every <nav> for rdc.html's own.
  */

  // The headings in PROJECT_GROUPS order, each with its projects.
  function projectGroups() {
    const known = new Set(PROJECT_GROUPS.map(g => g.id));
    const groups = PROJECT_GROUPS.map(g => ({ ...g, projects: ALL_PROJECTS.filter(p => p.group === g.id) }));
    groups.push({ id: 'other', label: 'Other', projects: ALL_PROJECTS.filter(p => !known.has(p.group)) });
    return groups.filter(g => g.projects.length);
  }

  // Accents folded away and case ignored, so "arsredovisning" finds
  // Digital årsredovisning and "stammare" the guitar tuner.
  function foldForSearch(text) {
    return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  }

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

    // The page one is on keeps its place in the list, marked, but is not a
    // link: the list shows where one is without offering the page again.
    const here = './' + currentPage;
    const entry = p => p.href === here
      ? `<span class="nav-current" aria-current="page">${p.label}</span>`
      : `<a href="${p.href}">${p.label}</a>`;
    const home = here === './index.html'
      ? '<span class="nav-home nav-current" aria-current="page">home</span>'
      : '<a class="nav-home" href="./index.html">home</a>';
    const groups = projectGroups();

    const menu = document.createElement('div');
    menu.id = 'menu';
    menu.setAttribute('role', 'navigation');
    menu.setAttribute('aria-label', 'Site');
    menu.innerHTML = `
      <div class="nav-panel">
        <div class="nav-top">
          <div class="nav-find">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/></svg>
            <input type="search" class="nav-search" placeholder="Find a project" aria-label="Find a project"
                   autocomplete="off" spellcheck="false" enterkeyhint="go">
          </div>
          ${home}
        </div>
        <div class="nav-groups">
          <div class="nav-cols">${groups.map(g => `
            <div class="nav-group">
              <div class="nav-group-label" id="nav-group-${g.id}">${g.label}</div>
              <ul aria-labelledby="nav-group-${g.id}">${g.projects.map(p => `
                <li data-project="${ALL_PROJECTS.indexOf(p)}">${entry(p)}</li>`).join('')}
              </ul>
            </div>`).join('')}
          </div>
          <p class="nav-empty" role="status"></p>
        </div>
      </div>`;
    toggle.insertAdjacentElement('afterend', menu);

    const panel = menu.querySelector('.nav-panel');
    const search = menu.querySelector('.nav-search');
    const scroller = menu.querySelector('.nav-groups');
    const empty = menu.querySelector('.nav-empty');

    // What the field looks in: a project's name and file name first, then its
    // description and its heading. A match on the name is the one Enter opens.
    const entries = [...menu.querySelectorAll('li[data-project]')].map(li => {
      const p = ALL_PROJECTS[li.dataset.project];
      const file = p.href.replace(/^\.\//, '').replace(/\.html$/, '').replace(/_/g, ' ');
      const heading = groups.find(g => g.projects.includes(p)).label;
      return {
        li,
        link: li.querySelector('a'),
        name: foldForSearch(p.label + ' ' + file),
        more: foldForSearch(p.desc + ' ' + heading),
      };
    });
    let picked = null;

    function pick(link) {
      if (picked) picked.classList.remove('nav-picked');
      picked = link;
      if (picked) picked.classList.add('nav-picked');
    }

    function filterMenu() {
      const words = foldForSearch(search.value).split(/\s+/).filter(Boolean);
      let shown = 0, byName = null, first = null;
      for (const e of entries) {
        const inName = words.every(w => e.name.includes(w));
        const found = inName || words.every(w => e.name.includes(w) || e.more.includes(w));
        e.li.hidden = !found;
        if (!found) continue;
        shown++;
        if (e.link && inName && !byName) byName = e.link;
        if (e.link && !first) first = e.link;
      }
      menu.querySelectorAll('.nav-group').forEach(g => {
        g.hidden = !g.querySelector('li:not([hidden])');
      });
      pick(words.length ? byName || first : null);
      empty.textContent = shown ? '' : `No project matches “${search.value.trim()}”.`;
    }
    search.addEventListener('input', filterMenu);

    // With a mouse or trackpad one can type straight away. On a touch screen
    // the keyboard would cover half the list, so the field waits for a tap.
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');

    function setMenuOpen(open) {
      if (open === menu.classList.contains('open')) return;
      toggle.classList.toggle('opened', open);
      menu.classList.toggle('open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!open) return;
      // Every opening starts from the whole list, scrolled to the top.
      search.value = '';
      filterMenu();
      scroller.scrollTop = 0;
      if (finePointer.matches) search.focus({ preventScroll: true });
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

    // Close when clicking anywhere outside the panel, the dimmed page included
    document.addEventListener('click', function (e) {
      if (!panel.contains(e.target) && !toggle.contains(e.target)) {
        closeMenu();
      }
    });

    // Close when the keyboard moves on past the menu, so focus never sits in
    // the page underneath while the menu still covers it.
    menu.addEventListener('focusout', function (e) {
      const to = e.relatedTarget;
      if (to && !menu.contains(to) && to !== toggle) closeMenu();
    });

    // Up and down walk the field and the projects in view, Enter in the field
    // opens the project it has picked out, and typing on a project goes on in
    // the field. Keys stop here, Escape apart, so that typing a name cannot
    // set off a page's own shortcuts underneath.
    menu.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') return;
      e.stopPropagation();
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const stops = [search, ...entries.filter(x => x.link && !x.li.hidden).map(x => x.link)];
        const at = stops.indexOf(document.activeElement);
        if (at < 0) return;
        const next = e.key === 'ArrowDown' ? (at === 0 && picked) || stops[at + 1] : stops[at - 1];
        if (!next) return;
        e.preventDefault();
        next.focus();
      } else if (e.key === 'Enter' && e.target === search) {
        if (!picked) return;
        e.preventDefault();
        picked.click();
      } else if (e.target !== search && e.key.length === 1 && e.key !== ' '
                 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        search.focus();
      }
    });
    menu.addEventListener('keyup', function (e) {
      if (e.key !== 'Escape') e.stopPropagation();
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
        <span class="footer-name">kvot ab |</span>
        <button type="button" class="icon-btn" data-on-click="kvot:toggleMap" aria-label="Show or hide the office map">
          ${svgIcon('0 0 32 32', ICON_ADDRESS, { title: 'address' })}
        </button>
        <span class="footer-address">valhallagatan 16 &bull; 753 34 &bull; uppsala</span> |
        <a href="tel:0733822313">${svgIcon('0 0 512 512', ICON_PHONE, { title: 'phone' })}</a>
        <a href="mailto:pa@kvotab.se">${svgIcon('0 0 512 512', ICON_MAIL, { title: 'mail' })}</a>
        <a href="https://linkedin.com/in/per-anders-ekstrom" target="_blank" rel="noopener noreferrer">${svgIcon('0 0 448 512', ICON_LINKEDIN, { title: 'linkedin' })}</a>
        <a href="https://www.mathworks.com/matlabcentral/profile/authors/718179" target="_blank" rel="noopener noreferrer">${svgIcon('0 0 24 24', ICON_MATLAB, { title: 'matlab' })}</a>
        <a href="https://github.com/kvotab" target="_blank" rel="noopener noreferrer">${svgIcon('0 0 98 96', ICON_GITHUB, { title: 'github' })}</a>
        ${extraIcons}
        | <a class="footer-notices" href="THIRD-PARTY-NOTICES.md" title="Licences of the libraries, fonts and data used here">notices</a>
      </span>
      <button class="theme-toggle" data-on-click="kvot:toggleTheme" title="${themeTitle}">${themeIcon}</button>
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

  /*
    A base tile layer that follows the light/dark switch. Leaflet keeps the
    tile grid and only re-requests the images, so the view does not jump or
    reset when the theme changes. The layer is returned detached: the caller
    decides when it goes on the map, and one that is currently off the map
    (proj.html while satellite is showing) still picks up the new style, so it
    comes back in the right theme rather than in the one it was built in.
  */
  function themedTileLayer(options = {}) {
    const layer = L.tileLayer(tileUrl(currentTheme()), options);
    document.documentElement.addEventListener('kvot-theme-change', e => {
      layer.setUrl(tileUrl(e.detail.theme));
    });
    return layer;
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
    themedTileLayer({ attribution: TILE_ATTRIBUTION, maxZoom: TILE_MAX_ZOOM }).addTo(map);
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

  // The same headings as the menu, each over a grid of its own cards. A card
  // ends with its page's file name, which says nothing a reader of the link
  // needs to hear again, so it is hidden from the link's spoken name.
  function renderProjectCards(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.innerHTML = projectGroups().map(g => `
      <section class="project-group" aria-labelledby="projects-${g.id}">
        <h3 class="project-group-title" id="projects-${g.id}">${g.label}</h3>
        <div class="project-grid">${g.projects.map(p => `
          <a class="project-card" href="${p.href}">
            <span class="project-card-title">${p.label}</span>
            <span class="project-card-desc">${p.desc}</span>
            <span class="project-card-path" aria-hidden="true">${p.href.replace(/^\.\//, '')}</span>
          </a>`).join('')}
        </div>
      </section>`).join('');
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
    tileUrl,
    themedTileLayer,
    currentTheme,
    TILE_ATTRIBUTION,
    TILE_MAX_ZOOM,
  };
})();
