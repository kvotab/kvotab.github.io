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
| [OrdinaryDiffEq.jl](https://github.com/SciML/OrdinaryDiffEq.jl) (ported to JavaScript) | MIT | `resources/js/ode_julia/LICENSE`, `kompartment/src/ode/julia/LICENSE` |
| Coordinate conversions by Arnold Andreasson (`gausskruger.js`, `lat_lon_conv.js`, `latlong.js`, `map.js`) | MIT | headers in the files |
| Error-function coefficients in `resources/js/erf.js` | Boost Software License 1.0 (John Maddock) | header in the file |
| CALERF (`resources/js/erf.f`, `erf.js`) | public domain (W. J. Cody, Netlib SPECFUN) | header in the file |
| Rawengulk Sans | SIL Open Font License 1.1 | `vendors/font/SIL Open Font License.txt` |

## Libraries loaded from public CDNs

jQuery and jQuery UI (MIT), MathJax (Apache-2.0), Leaflet (BSD-2-Clause),
SheetJS `xlsx` (Apache-2.0), SortableJS (MIT), h5wasm (BSD-3-Clause), JSZip
(MIT/GPLv3 dual), pdf.js (Apache-2.0), and — only when a model in Kompartment
asks for a SciPy solver — Pyodide (MPL-2.0) with the CPython (PSF), NumPy and
SciPy (BSD-3-Clause) builds it carries. They are fetched by the visitor's
browser from their publishers and are not redistributed here.

## Data

- **Radionuclide decay data** (`resources/js/rndecaydata.js`,
  `kompartment/src/domain/icrp107.js`) are from ICRP
  Publication 107, *Nuclear Decay Data for Dosimetric Calculations*, Annals of
  the ICRP 38(3), 2008, © ICRP. Dose coefficients are from ICRP Publications
  72 and 119 as cited on the page.
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
