# Third-party notices

kvotab.se is written and published by Kvot AB under the MIT licence (see
[LICENSE](LICENSE)). It ships, links to, or is built from the following work by
others. Each item keeps its own licence.

## Libraries served from this site (`vendors/`, `resources/js/`)

| Library | Licence | Notice |
|---|---|---|
| [Plotly.js](https://github.com/plotly/plotly.js) 2.27.0 | MIT | header in `vendors/js/plotly-2.27.0.min.js` |
| [Cytoscape.js](https://js.cytoscape.org/) | MIT | header in `vendors/js/cytoscape.umd.js` |
| [cytoscape-context-menus](https://github.com/iVis-at-Bilkent/cytoscape.js-context-menus) | MIT | `vendors/js/cytoscape-context-menus.js`, `vendors/css/cytoscape-context-menus.css` |
| [cytoscape-svg](https://github.com/kinimesi/cytoscape-svg) | MIT | `vendors/js/cytoscape-svg.js` |
| [jsTree](https://www.jstree.com/) | MIT | header in `vendors/js/jstree.min.js`; theme in `vendors/css/jstree/` |
| [math.js](https://mathjs.org/) | Apache-2.0 | `vendors/js/LICENSE-math.js.txt` |
| [FileSaver.js](https://github.com/eligrey/FileSaver.js) | MIT | `vendors/js/FileSaver.min.js` |
| [OrdinaryDiffEq.jl](https://github.com/SciML/OrdinaryDiffEq.jl) (ported to JavaScript, and from there to Python) | MIT | `resources/js/ode/julia/LICENSE`, `kompartment/src/ode/julia/LICENSE`, `kompartment/python/kompartment/engine/solvers/julia/LICENSE` |
| [Krylov.jl](https://github.com/JuliaSmoothOptimizers/Krylov.jl) (its GMRES, ported to JavaScript and Python) | MPL-2.0 | headers in `resources/js/ode/julia/core/krylov.js` (and its copies in `kompartment/src/ode/julia/core/` and `resources/js/ode-julia.js`), `kompartment/python/kompartment/engine/solvers/julia/krylov.py` |
| [GlobalSensitivity.jl](https://github.com/SciML/GlobalSensitivity.jl) (ported to JavaScript, and from there to Python), with the parts of [KernelDensity.jl](https://github.com/JuliaStats/KernelDensity.jl), [Interpolations.jl](https://github.com/JuliaMath/Interpolations.jl) and [ComplexityMeasures.jl](https://github.com/JuliaDynamics/ComplexityMeasures.jl) its methods use | MIT | `kompartment/src/domain/gsa.LICENSE`, `kompartment/python/kompartment/stats/gsa.LICENSE` |
| [SALib](https://github.com/SALib/SALib) (methods ported to JavaScript: PAWN, discrepancy, the radial design, Morris's optimal trajectories, bootstrap intervals, interaction effects; and from there to Python) | MIT | `kompartment/src/domain/salib.LICENSE`, `kompartment/python/kompartment/stats/salib.LICENSE` |
| Coordinate conversions by Arnold Andreasson (`gausskruger.js`, `lat_lon_conv.js`, `latlong.js`, `map.js`) | MIT | headers in the files |
| Error-function coefficients in `resources/js/erf.js` | Boost Software License 1.0 (John Maddock) | header in the file |
| CALERF (`resources/js/erf.f`, `erf.js`; the coefficients of its first interval also in `kompartment/src/parser/functions.js` and `kompartment/python/kompartment/stats/_normal.py`) | public domain (W. J. Cody, Netlib SPECFUN) | header in the file |
| Rawengulk Sans | SIL Open Font License 1.1 | `vendors/font/SIL Open Font License.txt` |

## Libraries loaded from public CDNs

jQuery and jQuery UI (MIT), MathJax (Apache-2.0), Leaflet (BSD-2-Clause),
SheetJS `xlsx` (Apache-2.0), SortableJS (MIT), h5wasm (BSD-3-Clause), JSZip
(MIT/GPLv3 dual), pdf.js (Apache-2.0), sql.js (MIT, with SQLite, public
domain), h5wasm-plugins (ISC; the compression libraries it is built from keep
their own licences) only when an HDF5 file in `rb.html` needs one of its
decompressors, and — only when a model in Kompartment
asks for a SciPy solver — Pyodide (MPL-2.0) with the CPython (PSF), NumPy and
SciPy (BSD-3-Clause) builds it carries. They are fetched by the visitor's
browser from their publishers and are not redistributed here.

## Work followed, not copied

- **Identifyer for Zotero** by Jonas Bååth
  (https://github.com/JonasBaath/identifyer-for-zotero): the idea behind
  `zoterify.html`, of converting a document's plain-text citations against the
  local Zotero database. The page's parser, matcher and word lists are written
  independently; no code of it is used.
- **docXMLater** by DiaTech (https://github.com/ItMeDiaTech/docXMLater, MIT):
  `resources/js/zoterify-docx.js` follows its way of editing an existing Word
  document under Track Changes. No code is copied from it.
- **myHDF5 and H5Web** by the ESRF (https://github.com/silx-kit/h5web, MIT):
  `rb.html` reads a large local file the way H5Web's h5wasm provider does,
  through WORKERFS in a worker, and loads HDF5 compression plugins by filter
  id as it does. `resources/js/rb-lazy.js` and `rb-lazy-worker.js` are written
  independently; no code is copied from them.

## Data

- **Radionuclide decay data** (`resources/js/rndecaydata.js`,
  `kompartment/src/domain/icrp107.js`) are from ICRP
  Publication 107, *Nuclear Decay Data for Dosimetric Calculations*, Annals of
  the ICRP 38(3), 2008, © ICRP. Dose coefficients are from ICRP Publications
  72 and 119 as cited on the page.
- **Dose coefficient data** (`resources/data/dose/`, used by
  `dose_coefficients.html`):
  - `icrp60/` is built by `scripts/gen-dose-icrp60.mjs` from the data files of
    DCAL (Eckerman, Leggett et al., ORNL/TM-2001/190), distributed by Oak Ridge
    National Laboratory: the biokinetic models of ICRP Publications 30, 56,
    67, 69 and 71 as DCAL holds them, the specific absorbed fractions of
    Cristy and Eckerman (ORNL/TM-8381, ORNL/TM-12351), and the ICRP
    Publication 38 decay data (*Radionuclide Transformations*, Annals of the
    ICRP 11–13, 1983, © ICRP).
  - `icrp103/decay/` is the ICRP Publication 107 decay data, read from the
    ICRP-07 files of the publication's supplementary data on the ICRP's site
    (with the index file of its corrigenda, 2021), Copyright © 2008 A. Endo
    and K.F. Eckerman, used for non-profit purposes under their licence,
    whose two notices are distributed with the data
    (`resources/data/dose/icrp103/decay/LICENSE.TXT` and `LICENSE_DECDATA.TXT`).
  - `icrp103/saf/` holds the specific absorbed fractions and region masses of
    the supplementary data of ICRP Publications 133 and 155 (Annals of the
    ICRP 45(2), 2016, and 52(4), 2023, © ICRP), converted to binary form by
    `scripts/gen-dose-icrp103.mjs`.
  - `icrp103/elements.json` and `hrtm.json` are transcribed from ICRP
    Publication 158 (Annals of the ICRP 53(4–5), 2024, © ICRP) and the ICRP's
    consultation drafts of its Parts 2 and 3: absorption parameters,
    absorption fractions, systemic transfer coefficients and regional
    deposition. `icrp103/progeny.json` is transcribed from the sections on the
    treatment of radioactive progeny of ICRP Publications 134, 137, 141 and
    151 (*Occupational Intakes of Radionuclides* Parts 2–5, Annals of the ICRP
    45(3–4), 2016; 46(3–4), 2017; 48(2–3), 2019; 51(1–2), 2022, © ICRP): the
    models that progeny formed in the body follow.
    `icrp103/radon.json` holds the inputs of Publication 158 for radon and
    thoron in homes (Tables 32.1–32.3 and C.1, the lung-air volumes of Table
    C.3), and `resources/js/dose/radon.js` the potential alpha energies and
    activity ratios of Publication 137 (Annex A; Annals of the ICRP 46(3–4),
    2017), © ICRP; the ICRP's tables of doses per exposure are not included.
    `resources/js/dose/risk.js` holds the nominal risk coefficients, the
    lethality, quality-of-life and life-lost factors, and the printed
    detriment tables of ICRP Publications 60 (Annex B, Tables 3 and 4;
    Annals of the ICRP 21(1–3), 1991) and 103 (Annex A, Table 1; Annals of
    the ICRP 37(2–4), 2007), © ICRP, from which the page recalculates the
    detriment-adjusted nominal risk coefficients and with which it compares. The ICRP's own tables of dose
    coefficients are not included; the tests compare with local copies of
    them and of the electronic annex of Publication 158 (ICRP InMoP
    Electronic Annex), which the page names as their source.
- **Nuclear structure and decay data** (`resources/data/ensdf/`) are built from
  the Evaluated Nuclear Structure Data File (ENSDF), maintained by the National
  Nuclear Data Center, Brookhaven National Laboratory, for the international
  Nuclear Structure and Decay Data network
  (https://www.nndc.bnl.gov/ensdf/). The release is named on `ensdf.html`;
  the data are read as published and not altered, except where the page says a
  value is inferred. Element names are those of IUPAC. `nndc.js` there lists
  the releases in NNDC's archive (https://www.nndc.bnl.gov/ensdfarchivals/) by
  file name and link only; the files themselves are downloaded from NNDC by the
  visitor.
- **Chemical element data** (`resources/js/rndatatree.js`: names, origins of
  names, atomic weights, densities, melting and boiling points) are adapted
  from Wikipedia's *List of chemical elements* and the element articles,
  available under the Creative Commons Attribution-ShareAlike 4.0 licence
  (https://creativecommons.org/licenses/by-sa/4.0/).
- **Map tiles** are © OpenStreetMap contributors (ODbL) via Jawg Maps;
  **transit data** are from Trafiklab (CC BY) and Trafikverket. Both are
  credited on the pages that use them.
- **Swedish taxonomy and SRU field definitions** (`arsred-taxonomi.js`,
  `sru-data.js`) are generated from Bolagsverket's and Skatteverket's public
  specifications.
