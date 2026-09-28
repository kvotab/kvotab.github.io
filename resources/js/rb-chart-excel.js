/* ==========================================================================
   RB CHART - the chart as an Excel workbook
   --------------------------------------------------------------------------
   The chart's "Download data and chart in Excel" button. The workbook has two
   sheets:

     Chart  the chart as the page draws it: the same lines in the same colours,
            widths and dashes; the same axes, lin or log, over the range on
            screen with the ticks Plotly placed and labelled as Plotly labels
            them; the same legend in the same order, left out for what the
            page leaves out of it; the same font. Several groups drawn a panel
            each are a chart each, stacked as the panels are, the panel's
            label over it. CI and SEM bands are drawn as their two edges, and
            a background overlay's phases as coloured bands behind the lines.
     Data   what the chart is drawn from, and what its series refer to: a time
            column, then a column per line with its band edges beside it,
            under the line's name and unit, and under its panel's label or its
            file when there are several; a block of columns per time axis
            when the files do not share one; the overlay's phases in a table
            of their own.

   What is drawn is read from Plotly itself, _fullData and _fullLayout: the
   colour a line was given by default, the range autorange chose, the ticks
   it placed. The colours around the lines are the light theme's whatever the
   page is in, since a workbook is printed on white.

   What Excel cannot do the same way: fill between two lines (a band is its
   two edges, drawn light), stretch a phase with the chart (a phase is a line
   as wide as the phase is at the size exported), and write a log axis's
   10⁻¹¹ (it writes 1E-11). A linear axis's 1.6×10⁻¹¹ and 0.1M it does
   write: the axis shows its values in units of 10⁻¹¹ or of a million
   (display units) and a number format adds the ×10⁻¹¹ or the M, with as
   many decimals on every label as the step needs (1.0×10⁻¹¹ where Plotly
   writes 1×10⁻¹¹; see xlTickFormat for why).

   The chart's XML is written here, not by xlsxwrite.js's own chart code,
   which can only point a series at columns in the order the data comes in.
   xlsxwrite.js packages it (addChart).
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/** The light theme's colours for what is not a line (rb-utils.js relayoutForTheme, getPanelBgColor). */
const XL_THEME = Object.freeze({
  text: '2D2416',
  muted: '7A6E62',
  grid: 'E5DDD5',
  minorGrid: 'F0EBE5',
  plot: 'FFFFFF',
  paper: 'FAF8F6'
});

/** Plotly's text, in points: 12px ticks and legend, 14px axis titles, 11px panel labels. */
const XL_FONT = Object.freeze({ tick: 9, title: 10.5, legend: 9, label: 8.25 });

/** The typeface the chart's text is in: the one the page draws with (xlTypeface), set per export. */
let _xlTypeface = 'Arial';

/** Plotly's SI prefixes by exponent: exponentformat 'SI', and 'B', which writes B for 10⁹. */
const XL_SI_PREFIX = Object.freeze({ '-15': 'f', '-12': 'p', '-9': 'n', '-6': 'µ', '-3': 'm', 3: 'k', 6: 'M', 9: 'G', 12: 'T' });
const XL_MINUS = '−';   // Plotly's minus sign in tick labels

const XL_PX_TO_PT = 0.75;
const XL_EMU_PER_PT = 12700;
const XL_DASH = Object.freeze({
  solid: 'solid', dot: 'sysDot', dash: 'dash', longdash: 'lgDash', dashdot: 'dashDot', longdashdot: 'lgDashDot'
});
/** How a band's edges are drawn: thin and light, in the colour of the line. */
const XL_BAND = Object.freeze({ ci: { widthPt: 0.75, alpha: 0.55, dash: 'solid' }, sem: { widthPt: 0.75, alpha: 0.55, dash: 'sysDot' } });
/** Where the data starts on the Data sheet: rows above it hold its description. */
const XL_DATA_SHEET = 'Data';
const XL_CHART_SHEET = 'Chart';

/* ── small tools ──────────────────────────────────────────────────────── */

function xlEscape(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/**
 * Plotly titles may carry <sup>, <sub>, <br> and entities; a chart title is
 * text. A no-break space stays one: the page's "Iter. 3" has one, and the
 * name in the workbook is the name in the page's legend.
 */
function xlPlainText(s) {
  const div = document.createElement('div');
  div.innerHTML = String(s || '').replace(/<br\s*\/?>/gi, ' ');   // parsed, never attached
  return div.textContent.replace(/[ \t\r\n\f]+/g, ' ').trim();
}

let _xlColorProbe = null;

/** A CSS colour as { hex: 'RRGGBB', alpha }, whatever CSS spelling Plotly used. */
function xlColor(css, fallback = '000000') {
  let m = /^#([0-9a-f]{3,8})$/i.exec(String(css || '').trim());
  if (!m) {
    if (!_xlColorProbe) {
      _xlColorProbe = document.createElement('span');
      _xlColorProbe.style.display = 'none';
      document.body.appendChild(_xlColorProbe);
    }
    _xlColorProbe.style.color = '';
    _xlColorProbe.style.color = String(css || '');
    const rgb = /rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)/i.exec(
      _xlColorProbe.style.color ? getComputedStyle(_xlColorProbe).color : '');
    if (!rgb) return { hex: fallback, alpha: 1 };
    const hex = [rgb[1], rgb[2], rgb[3]].map(v => Math.round(Number(v)).toString(16).padStart(2, '0')).join('');
    let alpha = rgb[4] === undefined ? 1 : parseFloat(rgb[4]) / (rgb[4].endsWith('%') ? 100 : 1);
    return { hex: hex.toUpperCase(), alpha: Math.max(0, Math.min(1, alpha)) };
  }
  let h = m[1];
  if (h.length === 3 || h.length === 4) h = h.split('').map(c => c + c).join('');
  return { hex: h.slice(0, 6).toUpperCase(), alpha: h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1 };
}

function xlNumber(v) {
  const n = typeof v === 'number' ? v : (v === null || v === undefined || v === '' ? NaN : Number(v));
  return isFinite(n) ? n : null;
}

/** The layout key of a trace's axis: 'x' -> 'xaxis', 'y3' -> 'yaxis3'. */
function xlAxisKey(ref, letter) {
  const m = /^[xy](\d*)$/.exec(ref || letter);
  return `${letter}axis${m && m[1] ? m[1] : ''}`;
}

/** The unit in a title such as "total (Sv/year)"; a title that is only a unit, as a panel's "Bq" is. */
function xlUnitOf(title) {
  const t = xlPlainText(title);
  const m = /\(([^()]*)\)\s*$/.exec(t);
  if (m) return m[1].trim();
  return t && !/\s/.test(t) && t.length <= 16 ? t : '';
}

function xlColumnName(col) {  // 0 -> A
  let s = '';
  for (let n = col + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}

function xlRef(col, row) {  // 0-based -> Data!$B$8
  return `${XL_DATA_SHEET}!$${xlColumnName(col)}$${row + 1}`;
}

function xlRange(col, row0, row1) {
  return `${XL_DATA_SHEET}!$${xlColumnName(col)}$${row0 + 1}:$${xlColumnName(col)}$${row1 + 1}`;
}

/** -11 -> ⁻¹¹ */
function xlSuperscript(n) {
  return String(n).replace('-', '⁻').replace(/\d/g, d => '⁰¹²³⁴⁵⁶⁷⁸⁹'[d]);
}

/** Text in a number format. */
function xlLiteral(s) {
  return `"${String(s).replace(/"/g, '')}"`;
}

/**
 * The first of Plotly's fonts this computer has, which is the one the page
 * draws in: Open Sans where it is installed, Verdana where it is not. Excel on
 * the same computer has the same fonts. A font is there when text in it is
 * not as wide as in the fallback.
 */
function xlTypeface(familyList) {
  const generic = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui']);
  const families = String(familyList || '').split(',').map(f => f.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
  try {
    const ctx = document.createElement('canvas').getContext('2d');
    const width = (font) => { ctx.font = font; return ctx.measureText('mmmmmmmmmmlli1WQ@#&').width; };
    for (const f of families) {
      if (generic.has(f.toLowerCase())) break;
      if (['monospace', 'serif'].some(g => width(`72px "${f}", ${g}`) !== width(`72px ${g}`))) {
        return f.replace(/\b[a-z]/g, c => c.toUpperCase());   // verdana -> Verdana
      }
    }
  } catch (err) {
    ignoreFailure('xlTypeface', err);
  }
  return 'Arial';
}

/* ── the chart, as Plotly drew it ─────────────────────────────────────── */

/** The decimals a tick step needs: 0.2 -> 1, 0.25 -> 2, 50 -> 0. */
function xlDecimals(step) {
  if (!(step > 0)) return 0;
  const s = String(Number(step.toPrecision(10)));
  const m = /^(\d+)(?:\.(\d+))?(?:e-(\d+))?$/.exec(s);
  if (!m) return 0;
  return Math.min(10, (m[2] ? m[2].length : 0) + (m[3] ? Number(m[3]) : 0));
}

/**
 * Plotly's tick labels as an Excel number format, with the display unit it
 * needs. Plotly writes a linear axis's labels over one exponent, its
 * _tickexponent: 1.6×10⁻¹¹ or 0.1M, and 0 as 0. Excel shows the values in
 * that unit and the format adds the ×10⁻¹¹ or the M, with the decimals the
 * step needs: Plotly's 1×10⁻¹¹ among 0.2, 0.4 ... is 1.0×10⁻¹¹ here. Not
 * General with the suffix, which would drop the zero: Excel then sizes the
 * labels as if General wrote every digit it can, and moves the plot area
 * right (56 px for 1.6×10⁻¹¹, so stacked panels no longer line up). A log
 * axis has a label a decade, each its own: 10, 100, 1000, 10k, 1M the same
 * in both; 10⁻¹¹ in Plotly is 1E-11 here, and 1 and 10 are written out as
 * Plotly does.
 */
function xlTickFormat(ax, log, max, majorUnit) {
  const fmt = ax.exponentformat || 'B';
  const si = fmt === 'SI' || fmt === 'B';
  if (log) {
    if (fmt === 'none') return { format: 'General', unit: null };
    if (!si) return { format: '[<0.5]0E+0;[<50]0;0E+0', unit: null };
    // Two conditions is all a format has: from 10⁹ up, B and M but no k.
    if (max >= 999999999.5) {
      return { format: `[>=999999999.5]0,,,${xlLiteral(fmt === 'B' ? 'B' : 'G')};[>=999999.5]0,,"M";General`, unit: null };
    }
    return { format: '[>=999999.5]0,,"M";[>=9999.5]0,"k";General', unit: null };
  }
  const e = Math.round(Number(ax._tickexponent) || 0);
  if (!e || fmt === 'none') return { format: 'General', unit: null };
  let suffix;
  if (si && XL_SI_PREFIX[e]) suffix = fmt === 'B' && e === 9 ? 'B' : XL_SI_PREFIX[e];
  else if (fmt === 'e' || fmt === 'E') suffix = `${fmt}${e > 0 ? '+' : XL_MINUS}${Math.abs(e)}`;
  else suffix = `×10${xlSuperscript(e)}`;
  const unit = Math.pow(10, e);
  const d = xlDecimals(majorUnit ? majorUnit / unit : 0);
  const digits = d ? `0.${'0'.repeat(d)}` : '0';
  const text = xlLiteral(suffix);
  return { format: `${digits}${text};${xlLiteral(XL_MINUS)}${digits}${text};0`, unit };
}

/** 10^v, without the round-off that puts a log axis's top at 999999.9999999979. */
function xlPow10(v) {
  return Number(Math.pow(10, v).toPrecision(12));
}

/**
 * An axis as Excel should draw it: the range on screen, the ticks Plotly
 * placed there, labelled as Plotly labels them.
 */
function xlAxis(ax, letter) {
  const log = ax.type === 'log';
  const r = (ax.range || [0, 1]).map(Number);
  let min = log ? xlPow10(r[0]) : r[0];
  let max = log ? xlPow10(r[1]) : r[1];
  if (min > max) { const t = min; min = max; max = t; }

  let majorUnit = null;
  if (log) {
    const d = Number(ax.dtick);
    majorUnit = isFinite(d) && d >= 1 ? Math.pow(10, Math.round(d)) : 10;
  } else {
    // Plotly's major ticks; its minor ones are in the same list, marked.
    const ticks = (ax._vals || []).filter(v => !v.minor).map(v => Number(v.x)).filter(isFinite).sort((a, b) => a - b);
    const steps = ticks.slice(1).map((t, i) => t - ticks[i]).filter(d => d > 0);
    if (steps.length) {
      steps.sort((a, b) => a - b);
      majorUnit = steps[Math.floor(steps.length / 2)];
      // Excel counts its ticks from the axis minimum, Plotly from zero. Start
      // the axis on a tick when that moves it by next to nothing.
      const first = ticks.find(t => t >= min);
      if (first !== undefined) {
        const onTick = first - Math.ceil((first - min) / majorUnit - 1e-9) * majorUnit;
        if (min - onTick <= 0.02 * (max - min)) min = onTick;
      }
    }
  }

  const { format, unit } = ax.showticklabels === false ? { format: 'General', unit: null }   // an upper panel's time axis
    : xlTickFormat(ax, log, Math.max(Math.abs(min), Math.abs(max)), majorUnit);

  return {
    letter,
    log,
    min,
    max,
    majorUnit,
    format,
    unit,
    title: xlPlainText(ax.title && ax.title.text),
    labels: ax.showticklabels !== false,
    grid: ax.showgrid !== false,
    minorGrid: !!(ax.minor && ax.minor.showgrid),
    ticks: ax.ticks === 'outside' ? 'out' : ax.ticks === 'inside' ? 'in' : 'none',
    minorTicks: ax.minor && ax.minor.ticks === 'outside' ? 'out' : ax.minor && ax.minor.ticks === 'inside' ? 'in' : 'none',
    line: ax.showline !== false
  };
}

/**
 * The chart in the plot div, as what Excel needs: its panels, each with its
 * axes, label and lines, the lines' bands, and the background overlay.
 *
 * @param {HTMLElement} gd - The plot div
 * @returns {Object|null} null when nothing is drawn
 */
function xlChartModel(gd) {
  const fl = gd._fullLayout;
  const fd = gd._fullData;
  if (!fl || !Array.isArray(fd)) return null;

  const lines = [];
  const bands = [];
  for (const ft of fd) {
    if (ft.visible !== true) continue;
    const ut = gd.data[ft.index] || {};
    if (ut._isSDOMHatch) continue;   // the SEM band's hatching: decoration
    const x = Array.from(ut.x || ft.x || [], xlNumber);
    const y = Array.from(ut.y || ft.y || [], xlNumber);
    if (!x.length) continue;
    if (ut._isCIBand || ut._isSDOMBand) {
      bands.push({ kind: ut._isCIBand ? 'ci' : 'sem', of: ut._bandOf || null, x, y, color: xlColor(ft.fillcolor),
        panel: `${ft.xaxis || 'x'}|${ft.yaxis || 'y'}` });
      continue;
    }
    const line = ft.line || {};
    const mode = String(ft.mode || 'lines');
    lines.push({
      name: xlPlainText(ft.name) || `Series ${lines.length + 1}`,
      panel: `${ft.xaxis || 'x'}|${ft.yaxis || 'y'}`,
      xaxis: ft.xaxis || 'x',
      yaxis: ft.yaxis || 'y',
      x,
      y,
      color: xlColor(line.color || (ft.marker && ft.marker.color)),
      widthPt: (Number(line.width) || 2) * XL_PX_TO_PT,
      dash: XL_DASH[line.dash] || (line.dash && line.dash !== 'solid' ? 'dash' : 'solid'),
      lines: mode.includes('lines'),
      markers: mode.includes('markers') ? { sizePt: (Number(ft.marker && ft.marker.size) || 6) * XL_PX_TO_PT } : null,
      smooth: line.shape === 'spline',
      legend: ft.showlegend !== false && !ut._hiddenFromLegend,
      rank: isFinite(ft.legendrank) ? Number(ft.legendrank) : 1000,   // the legend's order (rb sorts it by peak)
      bandKey: ut._bandKey || null,
      unit: ut._unit ? String(ut._unit) : '',
      fileKey: ut._fileKey ? String(ut._fileKey) : '',
      probabilistic: !!ut._isProbabilistic,
      realizations: Number(ut._numRealizations) || null,
      bands: []
    });
  }

  // Each band beside the line it belongs to: its first half is the upper edge,
  // its second the lower one, backwards (rb-chart-toggles.js draws them so).
  const loose = [];
  for (const b of bands) {
    const n = Math.floor(b.x.length / 2);
    const band = { kind: b.kind, x: b.x.slice(0, n), upper: b.y.slice(0, n), lower: b.y.slice(n).reverse(), color: b.color };
    const owner = b.of ? lines.find(l => l.bandKey === b.of) : null;
    if (owner) owner.bands.push(band);
    else loose.push(Object.assign(band, { panel: b.panel }));
  }

  // Panels, top to bottom.
  const panelKeys = [...new Set(lines.map(l => l.panel))];
  const panels = panelKeys.map((key) => {
    const [xref, yref] = key.split('|');
    const xa = fl[xlAxisKey(xref, 'x')] || fl.xaxis;
    const ya = fl[xlAxisKey(yref, 'y')] || fl.yaxis;
    const domain = (ya.domain || [0, 1]).map(Number);
    const label = panelKeys.length > 1
      ? (fl.annotations || []).find(a => a.xref === 'paper' && a.yref === 'paper' && Math.abs(Number(a.y) - domain[1]) < 1e-3)
      : null;
    return {
      key,
      domain,
      label: label ? xlPlainText(label.text) : '',
      x: xlAxis(xa, 'x'),
      y: xlAxis(ya, 'y'),
      lines: lines.filter(l => l.panel === key),
      loose: loose.filter(b => b.panel === key)
    };
  }).sort((a, b) => b.domain[1] - a.domain[1]);
  if (!panels.length) return null;

  // The background overlay's phases, on the first panel's x axis.
  const phases = [];
  const shapes = (fl.shapes || []).filter(s => s && s.name === BACKGROUND_SHAPE_NAME && s.xref === 'x');
  const segments = Array.isArray(gd.__bgSegments) ? gd.__bgSegments : [];
  for (const s of shapes) {
    const x0 = Number(s.x0);
    const x1 = Number(s.x1);
    if (!isFinite(x0) || !isFinite(x1)) continue;
    const seg = segments.find(g => Number(g.x0) === x0 && Number(g.x1) === x1)
      || segments.find(g => g.color === s.fillcolor && Math.abs(Number(g.x1) - x1) <= Math.abs(x1) * 1e-9);
    const name = seg && (seg.category !== undefined ? seg.category : seg.label);
    // Where the phase is drawn is the rectangle, which a log axis clamps
    // above zero; where it starts and ends is the segment's.
    const s0 = seg ? Number(seg.x0) : NaN;
    const s1 = seg ? Number(seg.x1) : NaN;
    const own = isFinite(s0) && isFinite(s1);
    phases.push({ name: name !== undefined && name !== null && name !== '' ? xlPlainText(name) : `Phase ${phases.length + 1}`,
      source: seg && seg.source ? String(seg.source) : '',
      x0: Math.min(x0, x1), x1: Math.max(x0, x1),
      from: own ? Math.min(s0, s1) : Math.min(x0, x1), to: own ? Math.max(s0, s1) : Math.max(x0, x1),
      color: xlColor(s.fillcolor) });
  }

  const margin = fl.margin || {};
  return {
    typeface: xlTypeface(fl.font && fl.font.family),
    width: Math.max(320, Math.round(fl.width || 960)),
    height: Math.max(220, Math.round(fl.height || 500)),
    margin: { l: margin.l || 80, r: margin.r || 150, t: margin.t || 25, b: margin.b || 60 },
    panels,
    phases
  };
}

/* ── the Data sheet ───────────────────────────────────────────────────── */

function xlSameValues(a, b) {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * Where every value goes: a block of columns per time axis, each starting
 * with its time column; in a block, each line and then its band edges. The
 * series the charts draw are listed with the cells they refer to.
 */
function xlDataLayout(model, firstRow) {
  const blocks = [];
  const blockOf = (x) => {
    let block = blocks.find(b => xlSameValues(b.x, x));
    if (!block) blocks.push(block = { x, columns: [] });
    return block;
  };
  const multiPanel = model.panels.length > 1;
  // Over the names, a row saying what each column is of: its panel, and its
  // file when the lines are of several ("Total (…b)" says which only in part).
  const multiFile = new Set(model.panels.flatMap(p => p.lines.map(l => l.fileKey)).filter(Boolean)).size > 1;
  const groupOf = (panel, line) => {
    const parts = multiPanel ? [panel.label] : [];
    if (multiFile && line && line.fileKey && !(multiPanel && panel.label.includes(line.fileKey))) parts.push(line.fileKey);
    return parts.filter(Boolean).join(' · ');
  };
  for (const panel of model.panels) {
    // A line's own unit; the axis's for one without, unless the axis lists
    // several (lines of groups in different units drawn in one chart).
    const axisUnit = xlUnitOf(panel.y.title);
    const panelUnit = axisUnit.includes(',') ? '' : axisUnit;
    for (const line of panel.lines) {
      const block = blockOf(line.x);
      const group = groupOf(panel, line);
      const unit = line.unit || panelUnit;
      block.columns.push({ header: line.name, group, unit, values: line.y, series: { panel, kind: 'line', line } });
      for (const band of line.bands) {
        const names = band.kind === 'ci' ? ['5%', '95%'] : ['− SEM', '+ SEM'];
        const b = blockOf(band.x);
        b.columns.push({ header: `${line.name} ${names[0]}`, group, unit, values: band.lower, series: { panel, kind: 'band', band, line, edge: 'lower' } });
        b.columns.push({ header: `${line.name} ${names[1]}`, group, unit, values: band.upper, series: { panel, kind: 'band', band, line, edge: 'upper' } });
      }
    }
    for (const band of panel.loose) {
      const block = blockOf(band.x);
      const group = groupOf(panel, null);
      const unit = panelUnit;
      const label = band.kind === 'ci' ? 'CI' : 'SEM';
      block.columns.push({ header: `${label} lower`, group, unit, values: band.lower, series: { panel, kind: 'band', band, edge: 'lower' } });
      block.columns.push({ header: `${label} upper`, group, unit, values: band.upper, series: { panel, kind: 'band', band, edge: 'upper' } });
    }
  }

  const hasGroupRow = multiPanel || multiFile;
  const groupRow = firstRow;
  const nameRow = firstRow + (hasGroupRow ? 1 : 0);
  const unitRow = nameRow + 1;
  const dataRow = unitRow + 1;

  let col = 0;
  for (const block of blocks) {
    block.timeCol = col;
    block.rows = [dataRow, dataRow + block.x.length - 1];
    col += 1;
    for (const c of block.columns) {
      c.col = col++;
      c.timeCol = block.timeCol;
      c.row0 = block.rows[0];
      c.nameRef = xlRef(c.col, nameRow);
      c.xRef = xlRange(block.timeCol, block.rows[0], block.rows[1]);
      c.yRef = xlRange(c.col, block.rows[0], block.rows[1]);
      c.x = block.x;
    }
    col += 1;   // a column between blocks
  }

  // The overlay's phases: a table to the right, two rows a phase -- the
  // middle of what of it is on screen, at the bottom and the top of the first
  // panel's y axis -- which is the line the chart draws as wide as the phase.
  let phaseTable = null;
  if (model.phases.length) {
    const c0 = col;
    const { x, y } = model.panels[0];
    const span = x.log ? Math.log10(x.max / x.min) : x.max - x.min;
    const rows = [];
    for (const p of model.phases) {
      const a = Math.max(p.x0, x.min);
      const b = Math.min(p.x1, x.max);
      if (!(b > a) || (x.log && a <= 0) || !(span > 0)) continue;
      const r = dataRow + 2 * rows.length;
      rows.push({ phase: p, row: r, mid: Number((x.log ? Math.sqrt(a * b) : (a + b) / 2).toPrecision(12)), bottom: y.min, top: y.max,
        fraction: x.log ? Math.log10(b / a) / span : (b - a) / span,
        nameRef: xlRef(c0, r), xRef: xlRange(c0 + 3, r, r + 1), yRef: xlRange(c0 + 4, r, r + 1) });
    }
    if (rows.length) {
      phaseTable = { col: c0, rows };
      col = c0 + 5;
    }
  }

  return { blocks, hasGroupRow, groupRow, nameRow, unitRow, dataRow, phaseTable, lastCol: col - 1 };
}

/** A column's number format: scientific where General would print a long decimal. */
function xlValueFormat(values) {
  let big = 0;
  let small = Infinity;
  for (const v of values) {
    if (v === null || v === 0) continue;
    const a = Math.abs(v);
    if (a > big) big = a;
    if (a < small) small = a;
  }
  return big >= 1e6 || (big > 0 && small < 1e-3) ? '0.000E+00' : 'General';
}

function xlWriteDataSheet(xlsx, model, layout, subject) {
  const S = XL_DATA_SHEET;
  const f = {
    title: xlsx.addFormat({ bold: true, fontSize: 13, fontColor: XL_THEME.text }),
    meta: xlsx.addFormat({ fontSize: 9, fontColor: XL_THEME.muted }),
    group: xlsx.addFormat({ bold: true, fontSize: 10, fontColor: XL_THEME.text, align: 'center' }),
    name: xlsx.addFormat({ bold: true, fontColor: XL_THEME.text, align: 'center', bottom: 1, bottomColor: XL_THEME.grid }),
    unit: xlsx.addFormat({ italic: true, fontSize: 9, fontColor: XL_THEME.muted, align: 'center' }),
    general: xlsx.addFormat({}),
    sci: xlsx.addFormat({ numFormat: '0.000E+00' })
  };

  xlsx.write(0, 0, subject.title, f.title, S);
  let row = 1;
  for (const line of subject.lines) xlsx.write(row++, 0, line, f.meta, S);

  const timeUnit = xlUnitOf(model.panels[model.panels.length - 1].x.title) || 'years';
  for (const block of layout.blocks) {
    xlsx.write(layout.nameRow, block.timeCol, 'Time', f.name, S);
    xlsx.write(layout.unitRow, block.timeCol, timeUnit, f.unit, S);
    block.x.forEach((v, i) => { if (v !== null) xlsx.write(layout.dataRow + i, block.timeCol, v, f.general, S); });
    xlsx.setColumn(block.timeCol, block.timeCol, 11, null, {}, S);

    // The group row, merged over each panel's run of columns.
    if (layout.hasGroupRow) {
      let start = 0;
      for (let i = 1; i <= block.columns.length; i++) {
        if (i === block.columns.length || block.columns[i].group !== block.columns[start].group) {
          const a = block.columns[start].col;
          const b = block.columns[i - 1].col;
          if (b > a) xlsx.mergeRange(layout.groupRow, a, layout.groupRow, b, block.columns[start].group, f.group, S);
          else xlsx.write(layout.groupRow, a, block.columns[start].group, f.group, S);
          start = i;
        }
      }
    }
    for (const c of block.columns) {
      xlsx.write(layout.nameRow, c.col, c.header, f.name, S);
      if (c.unit) xlsx.write(layout.unitRow, c.col, c.unit, f.unit, S);
      const fmt = xlValueFormat(c.values) === 'General' ? f.general : f.sci;
      c.values.forEach((v, i) => { if (v !== null) xlsx.write(layout.dataRow + i, c.col, v, fmt, S); });
      xlsx.setColumn(c.col, c.col, Math.min(26, Math.max(11, c.header.length + 2)), null, {}, S);
    }
  }

  if (layout.phaseTable) {
    const t = layout.phaseTable;
    const heads = ['Phase', 'From', 'To', 'Middle', 'Drawn from/to'];
    heads.forEach((h, i) => xlsx.write(layout.nameRow, t.col + i, h, f.name, S));
    xlsx.write(layout.unitRow, t.col + 1, timeUnit, f.unit, S);
    xlsx.write(layout.unitRow, t.col + 2, timeUnit, f.unit, S);
    for (const r of t.rows) {
      const vfmt = xlValueFormat([r.bottom, r.top]) === 'General' ? f.general : f.sci;
      xlsx.write(r.row, t.col, r.phase.name, f.general, S);
      xlsx.write(r.row, t.col + 1, r.phase.from, f.general, S);
      xlsx.write(r.row, t.col + 2, r.phase.to, f.general, S);
      xlsx.write(r.row, t.col + 3, r.mid, f.general, S);
      xlsx.write(r.row + 1, t.col + 3, r.mid, f.general, S);
      xlsx.write(r.row, t.col + 4, r.bottom, vfmt, S);
      xlsx.write(r.row + 1, t.col + 4, r.top, vfmt, S);
    }
    xlsx.setColumn(t.col, t.col, 16, null, {}, S);
    xlsx.setColumn(t.col + 1, t.col + 4, 12, null, {}, S);
  }

  // The names and units stay in view, and a single time column with them.
  xlsx.freezePanes(S, layout.dataRow, layout.blocks.length === 1 ? 1 : 0);
}

/* ── the chart's XML ──────────────────────────────────────────────────── */

function xlFill(color, alpha = 1) {
  const a = alpha < 1 ? `<a:alpha val="${Math.round(Math.max(0, alpha) * 100000)}"/>` : '';
  return `<a:solidFill><a:srgbClr val="${color}">${a}</a:srgbClr></a:solidFill>`;
}

function xlLn(color, widthPt, { alpha = 1, dash = 'solid', cap = 'rnd' } = {}) {
  const w = Math.round(Math.min(1584, Math.max(0, widthPt)) * XL_EMU_PER_PT);
  return `<a:ln w="${w}" cap="${cap}">${xlFill(color, alpha)}<a:prstDash val="${dash}"/><a:round/></a:ln>`;
}

const XL_NO_LINE = '<a:ln><a:noFill/></a:ln>';

function xlTextProps(pt, color, { bold = false, rot = null } = {}) {
  return `<a:bodyPr${rot === null ? '' : ` rot="${rot}" vert="horz"`}/><a:lstStyle/>`
    + `<a:p><a:pPr><a:defRPr sz="${Math.round(pt * 100)}" b="${bold ? 1 : 0}">${xlFill(color)}`
    + `<a:latin typeface="${xlEscape(_xlTypeface)}"/></a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p>`;
}

function xlRich(text, pt, color, { rot = null } = {}) {
  return `<c:tx><c:rich><a:bodyPr${rot === null ? '' : ` rot="${rot}" vert="horz"`}/><a:lstStyle/>`
    + `<a:p><a:pPr><a:defRPr sz="${Math.round(pt * 100)}" b="0">${xlFill(color)}<a:latin typeface="${xlEscape(_xlTypeface)}"/></a:defRPr></a:pPr>`
    + `<a:r><a:rPr lang="en-US" sz="${Math.round(pt * 100)}" b="0">${xlFill(color)}<a:latin typeface="${xlEscape(_xlTypeface)}"/></a:rPr>`
    + `<a:t>${xlEscape(text)}</a:t></a:r></a:p></c:rich></c:tx>`;
}

function xlManualLayout(target, x, y, w, h) {
  const n = v => Math.max(0, Math.min(1, v)).toFixed(5);
  return '<c:layout><c:manualLayout>'
    + (target ? `<c:layoutTarget val="${target}"/>` : '')
    + '<c:xMode val="edge"/><c:yMode val="edge"/>'
    + `<c:x val="${n(x)}"/><c:y val="${n(y)}"/>`
    + (w === undefined ? '' : `<c:w val="${n(w)}"/><c:h val="${n(h)}"/>`)
    + '</c:manualLayout></c:layout>';
}

function xlNumRef(ref, values) {
  let pts = '';
  values.forEach((v, i) => { if (v !== null) pts += `<c:pt idx="${i}"><c:v>${v}</c:v></c:pt>`; });
  return `<c:numRef><c:f>${ref}</c:f><c:numCache><c:formatCode>General</c:formatCode>`
    + `<c:ptCount val="${values.length}"/>${pts}</c:numCache></c:numRef>`;
}

function xlSeriesXml(i, s) {
  const marker = s.markers
    ? `<c:marker><c:symbol val="circle"/><c:size val="${Math.max(2, Math.min(72, Math.round(s.markers.sizePt)))}"/>`
      + `<c:spPr>${xlFill(s.color.hex, s.color.alpha)}${XL_NO_LINE}</c:spPr></c:marker>`
    : '<c:marker><c:symbol val="none"/></c:marker>';
  const line = s.lines === false ? XL_NO_LINE : xlLn(s.color.hex, s.widthPt, { alpha: s.color.alpha, dash: s.dash, cap: s.cap || 'rnd' });
  return `<c:ser><c:idx val="${i}"/><c:order val="${i}"/>`
    + `<c:tx><c:strRef><c:f>${s.nameRef}</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>${xlEscape(s.name)}</c:v></c:pt></c:strCache></c:strRef></c:tx>`
    + `<c:spPr>${line}</c:spPr>${marker}`
    + `<c:xVal>${xlNumRef(s.xRef, s.x)}</c:xVal><c:yVal>${xlNumRef(s.yRef, s.y)}</c:yVal>`
    + `<c:smooth val="${s.smooth ? 1 : 0}"/></c:ser>`;
}

function xlAxisXml(axis, id, crossId, position, { rotTitle = false } = {}) {
  let xml = `<c:valAx><c:axId val="${id}"/><c:scaling>`
    + (axis.log ? '<c:logBase val="10"/>' : '')
    + `<c:orientation val="minMax"/><c:max val="${axis.max}"/><c:min val="${axis.min}"/></c:scaling>`
    + `<c:delete val="0"/><c:axPos val="${position}"/>`;
  if (axis.grid) xml += `<c:majorGridlines><c:spPr>${xlLn(XL_THEME.grid, 0.75)}</c:spPr></c:majorGridlines>`;
  if (axis.minorGrid) xml += `<c:minorGridlines><c:spPr>${xlLn(XL_THEME.minorGrid, 0.75)}</c:spPr></c:minorGridlines>`;
  if (axis.title) {
    xml += `<c:title>${xlRich(axis.title, XL_FONT.title, XL_THEME.text, { rot: rotTitle ? -5400000 : null })}<c:overlay val="0"/></c:title>`;
  }
  xml += `<c:numFmt formatCode="${xlEscape(axis.format)}" sourceLinked="0"/>`
    + `<c:majorTickMark val="${axis.ticks}"/><c:minorTickMark val="${axis.minorTicks}"/>`
    + `<c:tickLblPos val="${axis.labels ? 'nextTo' : 'none'}"/>`
    + `<c:spPr>${axis.line ? xlLn(XL_THEME.grid, 0.75) : XL_NO_LINE}</c:spPr>`
    + `<c:txPr>${xlTextProps(XL_FONT.tick, XL_THEME.text)}</c:txPr>`
    + `<c:crossAx val="${crossId}"/><c:crosses val="min"/><c:crossBetween val="midCat"/>`
    + (axis.majorUnit ? `<c:majorUnit val="${axis.majorUnit}"/>` : '')
    + (axis.unit ? `<c:dispUnits><c:custUnit val="${axis.unit}"/></c:dispUnits>` : '')   // no label: the format says it
    + '</c:valAx>';
  return xml;
}

/**
 * One panel's chart part.
 *
 * @param {Object} panel
 * @param {Array} series - What it draws, in order, each with its refs and values
 * @param {Object} box - Its size and where its plot area, label and legend go, in px
 */
function xlChartXml(panel, series, box) {
  const W = box.width;
  const H = box.height;
  const title = panel.label
    ? `<c:title>${xlRich(panel.label, XL_FONT.label, XL_THEME.text)}`
      + `${xlManualLayout(null, box.plot.x / W, Math.max(0, box.plot.y - 18) / H)}<c:overlay val="1"/></c:title>`
    : '';

  const shown = series.filter(s => s.legend).length;
  let legend = '';
  if (shown) {
    const lx = (box.plot.x + box.plot.w + 12) / W;
    const lw = Math.max(0.05, 1 - lx - 6 / W);
    const lh = Math.min(1 - box.plot.y / H, (shown * 16 + 10) / H);
    legend = '<c:legend><c:legendPos val="r"/>'
      + series.map((s, i) => (s.legend ? '' : `<c:legendEntry><c:idx val="${i}"/><c:delete val="1"/></c:legendEntry>`)).join('')
      + xlManualLayout(null, lx, box.plot.y / H, lw, lh)
      + `<c:overlay val="0"/><c:spPr><a:noFill/>${XL_NO_LINE}</c:spPr>`
      + `<c:txPr>${xlTextProps(XL_FONT.legend, XL_THEME.text)}</c:txPr></c:legend>`;
  }

  const X = 50001;
  const Y = 50002;
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    + '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
    + 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    + '<c:date1904 val="0"/><c:lang val="en-US"/><c:roundedCorners val="0"/>'
    + `<c:chart>${title}<c:autoTitleDeleted val="${title ? 0 : 1}"/>`
    + `<c:plotArea>${xlManualLayout('inner', box.plot.x / W, box.plot.y / H, box.plot.w / W, box.plot.h / H)}`
    + '<c:scatterChart><c:scatterStyle val="lineMarker"/><c:varyColors val="0"/>'
    + series.map((s, i) => xlSeriesXml(i, s)).join('')
    + `<c:axId val="${X}"/><c:axId val="${Y}"/></c:scatterChart>`
    + xlAxisXml(panel.x, X, Y, 'b')
    + xlAxisXml(panel.y, Y, X, 'l', { rotTitle: true })
    + `<c:spPr>${xlFill(XL_THEME.plot)}${XL_NO_LINE}</c:spPr></c:plotArea>`
    + `${legend}<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>`
    + `<c:spPr>${xlFill(XL_THEME.paper)}${XL_NO_LINE}</c:spPr>`
    + `<c:txPr>${xlTextProps(XL_FONT.tick, XL_THEME.text)}</c:txPr>`
    + '</c:chartSpace>';
}

/**
 * Each panel's size and the boxes in it, in px, as the page lays them out:
 * Plotly's margins around the plot area, each panel its share of the height,
 * the gap above a panel for its label, the x axis's labels under the last.
 */
function xlPanelBoxes(model) {
  const { width: W, height: H, margin: m } = model;
  const plotW = W - m.l - m.r;
  const plotH = H - m.t - m.b;
  const boxes = [];
  model.panels.forEach((panel, i) => {
    const prev = model.panels[i - 1];
    const top = i === 0 ? m.t : Math.max(22, (prev.domain[0] - panel.domain[1]) * plotH);
    const h = Math.max(90, (panel.domain[1] - panel.domain[0]) * plotH);
    const last = i === model.panels.length - 1;
    const bottom = panel.x.labels || panel.x.title ? m.b : (last ? 12 : 4);
    const height = Math.round(top + h + bottom);
    boxes.push({ width: W, height, plot: { x: m.l, y: top, w: plotW, h } });
  });
  return boxes;
}

/** At most this many series in a chart: Excel's limit is 255. */
const XL_MAX_SERIES = 250;

/**
 * A column's stretches of rows a log axis can draw. A zero or a negative
 * value on a log axis makes Excel put up an alert every time the workbook is
 * opened, and a modal one: it holds up Excel until it is answered. Plotly
 * leaves such a point out and breaks the line there. So on a log axis a
 * column is drawn as its runs between them, each a series over its own rows;
 * a run a line cannot be drawn through (one point, no markers) is left out.
 * Empty cells are gaps either way and do not end a run.
 *
 * @returns {Array<[number, number]>} first and last index of each run
 */
function xlDrawableRuns(c, panel, markers) {
  const drawable = (v, log) => v === null || !log || v > 0;
  const runs = [];
  let start = -1;
  let points = 0;
  for (let i = 0; i <= c.values.length; i++) {
    const ok = i < c.values.length && drawable(c.x[i], panel.x.log) && drawable(c.values[i], panel.y.log);
    if (ok) {
      if (start < 0) { start = i; points = 0; }
      if (c.x[i] !== null && c.values[i] !== null) points += 1;
    } else if (start >= 0) {
      if (points >= (markers ? 1 : 2)) runs.push([start, i - 1]);
      start = -1;
    }
  }
  return runs;
}

/**
 * What a panel's chart draws, back to front: the overlay's phases, the band
 * edges, then the lines. Excel lists a legend in the order it draws, so the
 * lines are in the legend's order (legendrank), not the traces'; the Data
 * sheet keeps the traces' order, which is the file's.
 */
function xlPanelSeries(model, panel, layout, box) {
  const series = [];
  if (layout.phaseTable && panel === model.panels[0]) {
    for (const r of layout.phaseTable.rows) {
      series.push({ name: r.phase.name, nameRef: r.nameRef, xRef: r.xRef, yRef: r.yRef,
        x: [r.mid, r.mid], y: [r.bottom, r.top], color: r.phase.color, lines: true,
        widthPt: r.fraction * box.plot.w * XL_PX_TO_PT, dash: 'solid', cap: 'flat', legend: false });
    }
  }
  const columns = layout.blocks.flatMap(b => b.columns).filter(c => c.series.panel === panel);
  const bands = columns.filter(c => c.series.kind === 'band');
  const lines = columns.filter(c => c.series.kind === 'line').sort((a, b) => a.series.line.rank - b.series.line.rank);

  // Each column as one series, or on a log axis as its runs, the longest
  // kept when there are more than a chart holds.
  const log = panel.x.log || panel.y.log;
  const runsOf = new Map();
  if (log) {
    for (const c of [...bands, ...lines]) runsOf.set(c, xlDrawableRuns(c, panel, c.series.kind === 'line' && !!c.series.line.markers));
    const total = [...runsOf.values()].reduce((n, r) => n + r.length, 0);
    const room = XL_MAX_SERIES - series.length;
    if (total > room) {
      const share = Math.max(1, Math.floor(room / Math.max(1, runsOf.size)));
      for (const [c, runs] of runsOf) {
        if (runs.length <= share) continue;
        const keep = new Set(runs.map((r, i) => [r[1] - r[0], i]).sort((a, b) => b[0] - a[0]).slice(0, share).map(e => e[1]));
        runsOf.set(c, runs.filter((r, i) => keep.has(i)));
      }
    }
  }
  const pieces = (c) => (!log ? [{ xRef: c.xRef, yRef: c.yRef, x: c.x, y: c.values }]
    : runsOf.get(c).map(([a, b]) => ({ xRef: xlRange(c.timeCol, c.row0 + a, c.row0 + b), yRef: xlRange(c.col, c.row0 + a, c.row0 + b),
      x: c.x.slice(a, b + 1), y: c.values.slice(a, b + 1) })));

  for (const c of bands) {
    const look = XL_BAND[c.series.band.kind];
    const base = c.series.line ? c.series.line.color : c.series.band.color;
    for (const p of pieces(c)) {
      series.push(Object.assign({ name: c.header, nameRef: c.nameRef,
        color: { hex: base.hex, alpha: look.alpha }, widthPt: look.widthPt, dash: look.dash, lines: true, legend: false }, p));
    }
  }
  for (const c of lines) {
    const l = c.series.line;
    pieces(c).forEach((p, k) => {
      series.push(Object.assign({ name: c.header, nameRef: c.nameRef, color: l.color, widthPt: l.widthPt, dash: l.dash,
        lines: l.lines, markers: l.markers, smooth: l.smooth, legend: l.legend && k === 0 }, p));
    });
  }
  return series;
}

/* ── what the chart is of ─────────────────────────────────────────────── */

function xlChartSubject(model) {
  let paths = [];
  if (typeof selectedGroups !== 'undefined' && Array.isArray(selectedGroups) && selectedGroups.length > 1) {
    paths = selectedGroups.map(g => (g && g.path) || String(g));
  } else if (typeof multiSelectMode !== 'undefined' && multiSelectMode && Array.isArray(selectedDatasets) && selectedDatasets.length > 1) {
    paths = selectedDatasets.map(d => (d && d.path) || String(d));
  } else if (currentChartData && currentChartData.path) {
    paths = [currentChartData.path];
  } else if (selectedDatasetPath) {
    paths = [selectedDatasetPath];
  }
  // The files the lines are drawn from; the page's files when no line says.
  const drawn = [...new Set(model.panels.flatMap(p => p.lines.map(l => l.fileKey)).filter(Boolean))];
  const files = drawn.length ? drawn : (typeof getEffectiveFiles === 'function' ? getEffectiveFiles() : []);
  const lines = [];
  if (files.length) {
    const mode = typeof getTreeMode === 'function' && files.length > 1 ? getTreeMode() : 'separated';
    lines.push(`${files.length > 1 ? 'Files' : 'File'}: ${files.join(', ')}${mode !== 'separated' ? ` (${mode})` : ''}`);
  }
  lines.push(`Exported from the HDF5 Browser (kvotab.se) on ${new Date().toLocaleString('sv-SE').slice(0, 16)}`);

  const all = model.panels.flatMap(p => p.lines);
  const prob = all.filter(l => l.probabilistic);
  if (prob.length) {
    const n = [...new Set(prob.map(l => l.realizations).filter(Boolean))];
    lines.push(`Probabilistic lines are the mean over ${n.length === 1 ? n[0] : 'all'} realizations.`);
  }
  const kinds = new Set(all.flatMap(l => l.bands.map(b => b.kind)).concat(model.panels.flatMap(p => p.loose.map(b => b.kind))));
  if (kinds.has('ci')) lines.push('CI: the 5th and 95th percentiles over the realizations, drawn as the edges of the band.');
  if (kinds.has('sem')) lines.push('SEM: the mean ± its standard error, drawn as the edges of the band.');
  if (model.phases.length) {
    const sources = [...new Set(model.phases.map(p => p.source).filter(Boolean))];
    lines.push(`Background${sources.length ? `, from ${sources.join(', ')}` : ''}: each phase is drawn as a line as wide as `
      + 'the phase at the size exported; resizing the chart leaves them that wide.');
  }
  return { title: paths.join(', ') || 'Chart', lines, paths, files };
}

function xlFileName(subject) {
  const path = subject.paths.length === 1 ? subject.paths[0] : '';
  const several = typeof selectedGroups !== 'undefined' && Array.isArray(selectedGroups) && selectedGroups.length > 1 ? 'groups' : 'datasets';
  const leaf = path ? path.split('/').filter(Boolean).slice(-2).join('_') : (subject.paths.length ? `${subject.paths.length}_${several}` : 'chart');
  const file = subject.files.length === 1 ? subject.files[0].replace(/\.[^.]+$/, '') : '';
  const name = [leaf, file].filter(Boolean).join('_').replace(/[^\w.\-]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  return `${(name || 'chart').slice(0, 80)}.xlsx`;
}

/* ── the button ───────────────────────────────────────────────────────── */

/**
 * Export the chart on screen as an Excel workbook: the chart, drawn as the
 * page draws it, over its data. See the top of this file.
 *
 * @returns {Promise<void>}
 */
async function downloadChartDataAsExcel() {
  if (!currentChartData) {
    notifyUser('There is no chart data to export yet.');
    return;
  }
  if (!window.xlsxReady || !window.XlsxWriter) {
    reportFailure('downloadChartDataAsExcel', new Error('xlsxwrite.js did not load'),
      { userMessage: 'The Excel export library is not loaded. Reload the page and try again' });
    return;
  }

  try {
    const gd = document.getElementById('plotlyChart');
    const model = gd ? xlChartModel(gd) : null;
    if (!model) {
      notifyUser('Every trace is hidden. Show at least one before exporting.');
      return;
    }
    const subject = xlChartSubject(model);
    _xlTypeface = model.typeface;
    const xlsx = new XlsxWriter();

    // Chart first, so the workbook opens on it; it prints landscape, a page wide.
    xlsx.showGridlines(XL_CHART_SHEET, false);
    xlsx.fitToPage(XL_CHART_SHEET, { landscape: true });
    const layout = xlDataLayout(model, subject.lines.length + 2);
    xlWriteDataSheet(xlsx, model, layout, subject);

    const boxes = xlPanelBoxes(model);
    let y = 8;
    model.panels.forEach((panel, i) => {
      const box = boxes[i];
      const series = xlPanelSeries(model, panel, layout, box);
      xlsx.addChart(XL_CHART_SHEET, { width: box.width, height: box.height, xml: xlChartXml(panel, series, box) }, { x: 8, y });
      y += box.height;
    });

    await xlsx.saveAs(xlFileName(subject));
  } catch (err) {
    reportFailure('downloadChartDataAsExcel', err, { userMessage: 'The Excel export failed' });
  }
}
