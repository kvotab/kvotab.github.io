/**
 * xlsxwrite.js - JavaScript port of Matlab xlsxwrite function
 * Creates Excel XLSX files with data, charts, comments, and formatting
 * 
 * Works in both Node.js and browser environments using JSZip
 * 
 * @example
 * // Basic usage - write data to Excel file
 * const xlsx = new XlsxWriter('output.xlsx');
 * xlsx.writeData([[1, 2, 3], [4, 5, 6]], 'Sheet1');
 * await xlsx.save();
 * 
 * // With chart
 * const xlsx = new XlsxWriter('chart.xlsx');
 * const chart = xlsx.newChart();
 * chart.addSeries({ name: 'Series1', xValues: [1,2,3], yValues: [10,20,30] });
 * xlsx.writeData([[1,10], [2,20], [3,30]], 'Sheet1', { chart });
 * await xlsx.save();
 */

// Check environment and import JSZip if needed
let JSZip;
if (typeof window !== 'undefined' && window.JSZip) {
    JSZip = window.JSZip;
} else if (typeof require !== 'undefined') {
    try {
        JSZip = require('jszip');
    } catch (e) {
        console.warn('JSZip not found. Install with: npm install jszip');
    }
}

/**
 * Named colors mapping (HTML color names to hex)
 */
const NAMED_COLORS = {
    'black': '000000', 'navy': '000080', 'darkblue': '00008B', 'mediumblue': '0000CD',
    'blue': '0000FF', 'darkgreen': '006400', 'green': '008000', 'teal': '008080',
    'darkcyan': '008B8B', 'deepskyblue': '00BFFF', 'darkturquoise': '00CED1',
    'mediumspringgreen': '00FA9A', 'lime': '00FF00', 'springgreen': '00FF7F',
    'aqua': '00FFFF', 'cyan': '00FFFF', 'midnightblue': '191970', 'dodgerblue': '1E90FF',
    'lightseagreen': '20B2AA', 'forestgreen': '228B22', 'seagreen': '2E8B57',
    'darkslategray': '2F4F4F', 'limegreen': '32CD32', 'mediumseagreen': '3CB371',
    'turquoise': '40E0D0', 'royalblue': '4169E1', 'steelblue': '4682B4',
    'darkslateblue': '483D8B', 'mediumturquoise': '48D1CC', 'indigo': '4B0082',
    'darkolivegreen': '556B2F', 'cadetblue': '5F9EA0', 'cornflowerblue': '6495ED',
    'mediumaquamarine': '66CDAA', 'dimgray': '696969', 'slateblue': '6A5ACD',
    'olivedrab': '6B8E23', 'slategray': '708090', 'lightslategray': '778899',
    'mediumslateblue': '7B68EE', 'lawngreen': '7CFC00', 'chartreuse': '7FFF00',
    'aquamarine': '7FFFD4', 'maroon': '800000', 'purple': '800080', 'olive': '808000',
    'gray': '808080', 'grey': '808080', 'skyblue': '87CEEB', 'lightskyblue': '87CEFA',
    'blueviolet': '8A2BE2', 'darkred': '8B0000', 'darkmagenta': '8B008B',
    'saddlebrown': '8B4513', 'darkseagreen': '8FBC8F', 'lightgreen': '90EE90',
    'mediumpurple': '9370DB', 'darkviolet': '9400D3', 'palegreen': '98FB98',
    'darkorchid': '9932CC', 'yellowgreen': '9ACD32', 'sienna': 'A0522D',
    'brown': 'A52A2A', 'darkgray': 'A9A9A9', 'lightblue': 'ADD8E6',
    'greenyellow': 'ADFF2F', 'paleturquoise': 'AFEEEE', 'lightsteelblue': 'B0C4DE',
    'powderblue': 'B0E0E6', 'firebrick': 'B22222', 'darkgoldenrod': 'B8860B',
    'mediumorchid': 'BA55D3', 'rosybrown': 'BC8F8F', 'darkkhaki': 'BDB76B',
    'silver': 'C0C0C0', 'mediumvioletred': 'C71585', 'indianred': 'CD5C5C',
    'peru': 'CD853F', 'chocolate': 'D2691E', 'tan': 'D2B48C', 'lightgray': 'D3D3D3',
    'thistle': 'D8BFD8', 'orchid': 'DA70D6', 'goldenrod': 'DAA520',
    'palevioletred': 'DB7093', 'crimson': 'DC143C', 'gainsboro': 'DCDCDC',
    'plum': 'DDA0DD', 'burlywood': 'DEB887', 'lightcyan': 'E0FFFF',
    'lavender': 'E6E6FA', 'darksalmon': 'E9967A', 'violet': 'EE82EE',
    'palegoldenrod': 'EEE8AA', 'lightcoral': 'F08080', 'khaki': 'F0E68C',
    'aliceblue': 'F0F8FF', 'honeydew': 'F0FFF0', 'azure': 'F0FFFF',
    'sandybrown': 'F4A460', 'wheat': 'F5DEB3', 'beige': 'F5F5DC',
    'whitesmoke': 'F5F5F5', 'mintcream': 'F5FFFA', 'ghostwhite': 'F8F8FF',
    'salmon': 'FA8072', 'antiquewhite': 'FAEBD7', 'linen': 'FAF0E6',
    'lightgoldenrodyellow': 'FAFAD2', 'oldlace': 'FDF5E6', 'red': 'FF0000',
    'fuchsia': 'FF00FF', 'magenta': 'FF00FF', 'deeppink': 'FF1493',
    'orangered': 'FF4500', 'tomato': 'FF6347', 'hotpink': 'FF69B4',
    'coral': 'FF7F50', 'darkorange': 'FF8C00', 'lightsalmon': 'FFA07A',
    'orange': 'FFA500', 'lightpink': 'FFB6C1', 'pink': 'FFC0CB',
    'gold': 'FFD700', 'peachpuff': 'FFDAB9', 'navajowhite': 'FFDEAD',
    'moccasin': 'FFE4B5', 'bisque': 'FFE4C4', 'mistyrose': 'FFE4E1',
    'blanchedalmond': 'FFEBCD', 'papayawhip': 'FFEFD5', 'lavenderblush': 'FFF0F5',
    'seashell': 'FFF5EE', 'cornsilk': 'FFF8DC', 'lemonchiffon': 'FFFACD',
    'floralwhite': 'FFFAF0', 'snow': 'FFFAFA', 'yellow': 'FFFF00',
    'lightyellow': 'FFFFE0', 'ivory': 'FFFFF0', 'white': 'FFFFFF'
};

/**
 * Dash type mappings (Excel format)
 */
const DASH_TYPES = {
    'solid': 'solid',
    'dot': 'dot',
    'dash': 'dash',
    'lgDash': 'lgDash',
    'dashDot': 'dashDot',
    'lgDashDot': 'lgDashDot',
    'lgDashDotDot': 'lgDashDotDot',
    'sysDash': 'sysDash',
    'sysDot': 'sysDot',
    'sysDashDot': 'sysDashDot',
    'sysDashDotDot': 'sysDashDotDot'
};

/**
 * Convert column number to Excel column letter(s)
 * @param {number} column - 1-based column number
 * @returns {string} Column letter(s) (A, B, ..., Z, AA, AB, ...)
 */
function xlColumn(column) {
    let result = '';
    while (column > 0) {
        column--;
        result = String.fromCharCode(65 + (column % 26)) + result;
        column = Math.floor(column / 26);
    }
    return result;
}

/**
 * Convert Excel cell reference to row/column indices
 * @param {string|number|number[]} xlCell - Cell reference ('A1') or [row, col] array
 * @returns {{row: number, column: number}} 1-based row and column
 */
function xlCell2Ind(xlCell) {
    if (typeof xlCell === 'string') {
        const match = xlCell.match(/^([A-Z]+)(\d+)$/i);
        if (!match) return { row: 1, column: 1 };
        const letters = match[1].toUpperCase();
        const row = parseInt(match[2], 10);
        let column = 0;
        for (let i = 0; i < letters.length; i++) {
            column = column * 26 + (letters.charCodeAt(i) - 64);
        }
        return { row, column };
    } else if (Array.isArray(xlCell)) {
        return { row: xlCell[0] || 1, column: xlCell[1] || 1 };
    } else if (typeof xlCell === 'number') {
        return { row: xlCell, column: 1 };
    }
    return { row: 1, column: 1 };
}

/**
 * Convert color value to hex string
 * @param {string|number|number[]} colorValue - Color as name, hex, RGB array, or number
 * @returns {string} 6-character hex color string
 */
function getHexColor(colorValue) {
    if (colorValue === null || colorValue === undefined || 
        (typeof colorValue === 'number' && isNaN(colorValue))) {
        return '000000';
    }
    
    if (typeof colorValue === 'string') {
        const namedColor = NAMED_COLORS[colorValue.toLowerCase()];
        if (namedColor) return namedColor;
        // Remove # if present
        return colorValue.replace('#', '').toUpperCase();
    }
    
    if (Array.isArray(colorValue)) {
        // RGB array [r, g, b] (0-255)
        return colorValue.map(c => Math.round(c).toString(16).padStart(2, '0')).join('').toUpperCase();
    }
    
    if (typeof colorValue === 'number') {
        // MS Access color format (BGR)
        const r = colorValue & 0xFF;
        const g = (colorValue >> 8) & 0xFF;
        const b = (colorValue >> 16) & 0xFF;
        return [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('').toUpperCase();
    }
    
    return '000000';
}

/**
 * Escape XML special characters
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
function escapeXml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

/**
 * Generate unique ID
 * @returns {number} Random ID
 */
function generateId() {
    return Math.floor(Math.random() * 1e9);
}

/**
 * Deep merge objects
 * @param {Object} target - Target object
 * @param {Object} source - Source object
 * @returns {Object} Merged object
 */
function deepMerge(target, source) {
    const result = { ...target };
    for (const key of Object.keys(source)) {
        if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
            result[key] = deepMerge(result[key] || {}, source[key]);
        } else {
            result[key] = source[key];
        }
    }
    return result;
}

// ============================================================================
// Default Structure Factories
// ============================================================================

/**
 * Create default color structure
 */
function getDefaultColor(overrides = {}) {
    return deepMerge({
        option: 'Automatic',  // 'Automatic', 'None', 'Solid', 'Pattern'
        value: [0, 0, 0],
        transparency: 0
    }, overrides);
}

/**
 * Create default line structure
 */
function getDefaultLine(overrides = {}) {
    return deepMerge({
        color: getDefaultColor(),
        width: 1.5,
        compoundType: 'sng',
        dashType: 'solid',
        capType: 'rnd',
        joinType: 'round',
        beginType: 'none',
        beginWidth: 'med',
        beginLength: 'med',
        endType: 'none',
        endWidth: 'med',
        endLength: 'med'
    }, overrides);
}

/**
 * Create default font structure
 */
function getDefaultFont(overrides = {}) {
    return deepMerge({
        name: 'Calibri',
        size: 11,
        bold: false,
        italic: false,
        underline: 'none',
        color: getDefaultColor({ option: 'Solid', value: [0, 0, 0] }),
        cap: 'none',
        strike: 'noStrike',
        superscript: false,
        subscript: false,
        offset: 0
    }, overrides);
}

/**
 * Create default marker structure
 */
function getDefaultMarker(overrides = {}) {
    return deepMerge({
        option: 'Automatic',  // 'Automatic', 'NoMarker', 'Built-in'
        type: 'circle',
        size: 5,
        fillColor: getDefaultColor(),
        line: getDefaultLine({ width: 0.75 })
    }, overrides);
}

/**
 * Create default label structure
 */
function getDefaultLabel(overrides = {}) {
    return deepMerge({
        containsSeriesName: false,
        containsXValue: false,
        containsYValue: false,
        position: 'b',
        font: getDefaultFont({ size: 9 }),
        includeLegendKey: false,
        separator: ';',
        numberFormatCode: 'General',
        numberLinkedToSource: true,
        points: []
    }, overrides);
}

/**
 * Create default manual layout structure
 */
function getDefaultManualLayout(overrides = {}) {
    return deepMerge({
        layout: false,
        x: NaN,
        y: NaN,
        w: NaN,
        h: NaN
    }, overrides);
}

/**
 * Create default title structure
 */
function getDefaultTitle(overrides = {}) {
    return deepMerge({
        text: '',
        font: getDefaultFont(),
        fillColor: getDefaultColor(),
        line: getDefaultLine(),
        customAngle: 0,
        verticalText: 'horz'
    }, overrides);
}

/**
 * Create default axis structure
 */
function getDefaultAxis(overrides = {}) {
    return deepMerge({
        id: generateId(),
        visible: true,
        minimum: NaN,
        maximum: NaN,
        major: {
            unit: NaN,
            tickMark: 'out',
            gridLine: getDefaultLine({
                color: getDefaultColor({ option: 'Solid', value: [217, 217, 217] }),
                width: 0.75,
                dashType: 'solid'
            })
        },
        minor: {
            unit: NaN,
            tickMark: 'none',
            gridLine: getDefaultLine({
                color: getDefaultColor({ option: 'None', value: [217, 217, 217] }),
                width: 0.75,
                dashType: 'dash'
            })
        },
        crossesAt: NaN,
        crosses: 'autoZero',
        crossBetween: 'midCat',
        displayUnits: 'none',
        logBase: NaN,
        orientation: 'minMax',
        title: getDefaultTitle({ font: getDefaultFont({ size: 10, bold: true }) }),
        label: {
            position: 'nextTo',
            font: getDefaultFont({ size: 9 }),
            customAngle: 0,
            verticalText: 'horz'
        },
        numberFormatCode: 'General',
        numberLinkedToSource: true,
        line: getDefaultLine()
    }, overrides);
}

/**
 * Create default series structure
 */
function getDefaultSeries(overrides = {}) {
    return deepMerge({
        type: 'Scatter',  // 'Scatter', 'Line', 'Area', 'Bar'
        option: 'PrimaryAxis',  // 'PrimaryAxis', 'SecondaryAxis'
        order: NaN,
        name: { ref: '', text: '' },
        x: { ref: '', values: [] },
        y: { ref: '', values: [] },
        length: 0,
        line: getDefaultLine({ width: 1.5, color: getDefaultColor({ option: 'Solid' }) }),
        marker: getDefaultMarker(),
        legendVisible: true,
        label: getDefaultLabel()
    }, overrides);
}

/**
 * Create default shape structure
 */
function getDefaultShape(overrides = {}) {
    return deepMerge({
        fillColor: getDefaultColor(),
        line: getDefaultLine()
    }, overrides);
}

/**
 * Create default legend structure  
 */
function getDefaultLegend(overrides = {}) {
    return deepMerge({
        position: 'r',  // 'none', 'b', 'l', 'r', 't', 'tr'
        overlay: false,
        font: getDefaultFont({ size: 10 }),
        fillColor: getDefaultColor({ option: 'Solid', value: [255, 255, 255] }),
        line: getDefaultLine(),
        manual: getDefaultManualLayout()
    }, overrides);
}

/**
 * Create default chart structure
 */
function getDefaultChart(overrides = {}) {
    return deepMerge({
        scatterStyle: 'lineMarker',
        grouping: 'standard',
        barDir: 'col',
        gapWidth: 150,
        overlap: 100,
        height: 288,
        width: 480,
        x: 0,
        y: 0,
        title: getDefaultTitle({ font: getDefaultFont({ size: 14 }) }),
        xAxis: getDefaultAxis(),
        yAxis: getDefaultAxis({ title: { customAngle: -90 } }),
        x2Axis: getDefaultAxis(),
        y2Axis: getDefaultAxis({ title: { customAngle: -90 } }),
        plotArea: getDefaultShape({
            fillColor: getDefaultColor({ option: 'Solid', value: [255, 255, 255] }),
            line: getDefaultLine({ color: getDefaultColor({ option: 'None' }) }),
            manual: getDefaultManualLayout()
        }),
        chartArea: getDefaultShape({
            fillColor: getDefaultColor({ option: 'Solid', value: [255, 255, 255] }),
            line: getDefaultLine({ color: getDefaultColor({ option: 'None' }) })
        }),
        legend: getDefaultLegend(),
        series: []
    }, overrides);
}

/**
 * Create default comment structure
 */
function getDefaultComment(overrides = {}) {
    return deepMerge({
        author: '',
        ref: '',
        visible: false,
        text: '',
        color: 'FFFFE1',
        opacity: 1
    }, overrides);
}

/**
 * Create default text box structure
 */
function getDefaultTextBox(overrides = {}) {
    return deepMerge({
        text: '',
        x: 0,
        y: 0,
        w: 1,
        h: 1,
        font: getDefaultFont(),
        fillColor: getDefaultColor(),
        line: getDefaultLine()
    }, overrides);
}

// ============================================================================
// XML Generation Functions
// ============================================================================

/**
 * Generate XML fill element
 */
function getXMLFill(color) {
    if (!color || !color.option) return '';
    
    switch (color.option) {
        case 'Automatic':
            return '';
        case 'None':
            return '<a:noFill/>';
        case 'Solid':
            if (isNaN(color.value) || color.value === null) {
                return '<a:noFill/>';
            }
            const hex = getHexColor(color.value);
            let alpha = '';
            if (color.transparency > 0) {
                alpha = `<a:alpha val="${Math.round((100 - color.transparency) * 1000)}"/>`;
            }
            return `<a:solidFill><a:srgbClr val="${hex}">${alpha}</a:srgbClr></a:solidFill>`;
        case 'Pattern':
            if (color.pattern) {
                return `<a:pattFill prst="${color.pattern.type}">` +
                    `<a:fgClr><a:srgbClr val="${getHexColor(color.pattern.foregroundColorValue)}"/></a:fgClr>` +
                    `<a:bgClr><a:srgbClr val="${getHexColor(color.pattern.backgroundColorValue)}"/></a:bgClr>` +
                    `</a:pattFill>`;
            }
            return '';
        default:
            return '';
    }
}

/**
 * Generate XML line element
 */
function getXMLLine(line) {
    if (!line || !line.color) return '';
    
    switch (line.color.option) {
        case 'Automatic':
            return '';
        case 'None':
            return '<a:ln><a:noFill/></a:ln>';
        case 'Solid':
            const dashType = DASH_TYPES[line.dashType] || 'solid';
            return `<a:ln cap="${line.capType}" cmpd="${line.compoundType}" w="${Math.round(line.width * 12700)}">` +
                getXMLFill(line.color) +
                `<a:prstDash val="${dashType}"/>` +
                `<a:headEnd w="${line.beginWidth}" type="${line.beginType}" len="${line.beginLength}"/>` +
                `<a:tailEnd w="${line.endWidth}" type="${line.endType}" len="${line.endLength}"/>` +
                `</a:ln>`;
        default:
            return '';
    }
}

/**
 * Generate XML shape properties
 */
function getXMLShape(shape) {
    return `<c:spPr>${getXMLFill(shape.fillColor)}${getXMLLine(shape.line)}</c:spPr>`;
}

/**
 * Generate XML font element
 */
function getXMLFont(font, tag = 'defRPr') {
    let baseline = 0;
    if (font.superscript) baseline = 30000;
    else if (font.subscript) baseline = -25000;
    else baseline = font.offset * 100;
    
    let attrs = `lang="en-US" sz="${Math.round(100 * font.size)}" b="${font.bold ? 1 : 0}" i="${font.italic ? 1 : 0}" baseline="${baseline}"`;
    
    if (font.underline !== 'none') attrs += ` u="${font.underline}"`;
    if (font.strike !== 'noStrike') attrs += ` strike="${font.strike}"`;
    if (font.cap !== 'none') attrs += ` cap="${font.cap}"`;
    
    let fontName = '';
    if (font.name && font.name !== 'Automatic') {
        fontName = `<a:latin typeface="${font.name}" pitchFamily="2" charset="2"/>`;
    }
    
    return `<a:${tag} ${attrs}>${getXMLFill(font.color)}${fontName}</a:${tag}>`;
}

/**
 * Generate XML text properties
 */
function getXMLTextProperties(text) {
    let bodyPr = '<a:bodyPr';
    if (text.verticalText) bodyPr += ` vert="${text.verticalText}"`;
    if (text.customAngle) bodyPr += ` rot="${text.customAngle * 60000}"`;
    bodyPr += '/>';
    
    return `<c:txPr>${bodyPr}<a:lstStyle/><a:p><a:pPr>${getXMLFont(text.font)}</a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>`;
}

/**
 * Generate XML title element
 */
function getXMLTitle(title) {
    if (!title.text) return '';
    
    return `<c:title><c:tx><c:rich>` +
        `<a:bodyPr vert="${title.verticalText}" rot="${title.customAngle * 60000}"/>` +
        `<a:lstStyle/><a:p><a:pPr><a:defRPr/></a:pPr>` +
        `<a:r>${getXMLFont(title.font, 'rPr')}<a:t>${escapeXml(title.text)}</a:t></a:r>` +
        `</a:p></c:rich></c:tx><c:layout/><c:overlay val="0"/>${getXMLShape(title)}</c:title>`;
}

/**
 * Generate XML manual layout
 */
function getXMLManualLayout(manual, layoutTarget) {
    if (!manual || !manual.layout) {
        return '<c:layout/>';
    }
    
    let xml = '<c:layout><c:manualLayout>';
    if (layoutTarget) xml += `<c:layoutTarget val="${layoutTarget}"/>`;
    xml += '<c:xMode val="edge"/><c:yMode val="edge"/>';
    xml += `<c:x val="${manual.x}"/><c:y val="${manual.y}"/>`;
    xml += `<c:w val="${manual.w}"/><c:h val="${manual.h}"/>`;
    xml += '</c:manualLayout></c:layout>';
    return xml;
}

// ============================================================================
// Main XlsxWriter Class
// ============================================================================

class XlsxWriter {
    constructor(filename = 'output.xlsx') {
        this.filename = filename.endsWith('.xlsx') ? filename : filename + '.xlsx';
        this.zip = new JSZip();
        this.sheets = [];
        this.sharedStrings = [];
        this.charts = [];
        this.comments = [];
        this.currentSheetId = 0;
    }
    
    /**
     * Create a new chart configuration
     * @param {Object} overrides - Chart property overrides
     * @returns {Object} Chart configuration object
     */
    newChart(overrides = {}) {
        return getDefaultChart(overrides);
    }
    
    /**
     * Create a new series configuration
     * @param {Object} overrides - Series property overrides
     * @returns {Object} Series configuration object
     */
    newSeries(overrides = {}) {
        return getDefaultSeries(overrides);
    }
    
    /**
     * Create a new comment configuration
     * @param {Object} overrides - Comment property overrides
     * @returns {Object} Comment configuration object
     */
    newComment(overrides = {}) {
        return getDefaultComment(overrides);
    }
    
    /**
     * Add a series to a chart from data
     * @param {Object} chart - Chart configuration
     * @param {Object} options - Series options
     */
    addSeriesToChart(chart, options) {
        const series = this.newSeries({
            name: { text: options.name || `Series${chart.series.length + 1}` },
            x: { values: options.xValues || [] },
            y: { values: options.yValues || [] },
            length: options.yValues ? options.yValues.length : 0,
            line: options.line || getDefaultLine({
                color: getDefaultColor({ option: 'Solid', value: options.color || this._getDefaultSeriesColor(chart.series.length) })
            }),
            marker: options.marker || getDefaultMarker({ option: options.showMarkers ? 'Built-in' : 'NoMarker' })
        });
        
        chart.series.push(series);
        return series;
    }
    
    /**
     * Get default color for series by index
     */
    _getDefaultSeriesColor(index) {
        const colors = [
            [79, 129, 189],   // Blue
            [192, 80, 77],    // Red
            [155, 187, 89],   // Green
            [128, 100, 162],  // Purple
            [75, 172, 198],   // Cyan
            [247, 150, 70],   // Orange
        ];
        return colors[index % colors.length];
    }
    
    /**
     * Write data to a worksheet
     * @param {Array} data - 2D array of data
     * @param {string|number} sheet - Sheet name or index
     * @param {Object} options - Write options
     */
    writeData(data, sheet = 'Sheet1', options = {}) {
        const sheetName = typeof sheet === 'number' ? `Sheet${sheet}` : sheet;
        const { row: startRow, column: startCol } = xlCell2Ind(options.xlPos || 'A1');
        
        // Add header if provided
        let fullData = data;
        if (options.header && Array.isArray(options.header)) {
            fullData = [options.header, ...data];
        }
        
        // Process data and collect shared strings
        const processedData = [];
        for (let r = 0; r < fullData.length; r++) {
            const row = fullData[r];
            const processedRow = [];
            for (let c = 0; c < row.length; c++) {
                const cell = row[c];
                let cellData = { value: cell, type: 'n' };
                
                if (cell === null || cell === undefined) {
                    cellData = { value: '', type: 'n' };
                } else if (typeof cell === 'string') {
                    if (cell.startsWith('=')) {
                        // Formula
                        cellData = { value: cell.substring(1), type: 'str', isFormula: true };
                    } else {
                        // Shared string
                        let idx = this.sharedStrings.indexOf(cell);
                        if (idx === -1) {
                            idx = this.sharedStrings.length;
                            this.sharedStrings.push(cell);
                        }
                        cellData = { value: idx, type: 's' };
                    }
                } else if (typeof cell === 'boolean') {
                    cellData = { value: cell ? 1 : 0, type: 'b' };
                } else if (typeof cell === 'number') {
                    if (cell === Infinity) cellData.value = 9.99999999999999E+307;
                    else if (cell === -Infinity) cellData.value = -9.99999999999999E+307;
                    else if (isNaN(cell)) cellData.value = '';
                }
                
                processedRow.push(cellData);
            }
            processedData.push(processedRow);
        }
        
        this.sheets.push({
            name: sheetName,
            data: processedData,
            startRow,
            startCol,
            chart: options.chart || null,
            comments: options.comments || []
        });
        
        return this;
    }
    
    /**
     * Generate the sheet data XML
     */
    _generateSheetDataXML(sheet) {
        let xml = '';
        const { data, startRow, startCol } = sheet;
        
        for (let r = 0; r < data.length; r++) {
            const row = data[r];
            // Skip completely empty rows
            if (!row || row.length === 0) continue;
            
            // Check if row has any non-empty cells
            const hasContent = row.some(cell => 
                cell && (cell.value !== '' && cell.value !== null && cell.value !== undefined)
            );
            if (!hasContent) continue;
            
            const rowNum = startRow + r;
            const maxCol = startCol + row.length - 1;
            xml += `<row r="${rowNum}" spans="${startCol}:${maxCol}">`;
            
            for (let c = 0; c < row.length; c++) {
                const cell = row[c];
                if (!cell) continue;
                
                const colNum = startCol + c;
                const cellRef = xlColumn(colNum) + rowNum;
                
                if (cell.isFormula) {
                    xml += `<c r="${cellRef}"><f>${escapeXml(cell.value)}</f></c>`;
                } else if (cell.value === '' || cell.value === null || cell.value === undefined) {
                    // Skip empty cells
                } else if (cell.type === 'n') {
                    // Number - don't include t attribute for numbers
                    xml += `<c r="${cellRef}"><v>${cell.value}</v></c>`;
                } else {
                    xml += `<c r="${cellRef}" t="${cell.type}"><v>${cell.value}</v></c>`;
                }
            }
            
            xml += '</row>';
        }
        
        return xml;
    }
    
    /**
     * Generate the chart XML
     */
    _generateChartXML(chart, sheetName, dataInfo) {
        let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        xml += '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">';
        xml += '<c:date1904 val="0"/>';
        xml += '<c:lang val="en-US"/>';
        xml += '<c:roundedCorners val="0"/>';
        xml += '<c:chart>';
        
        // Chart title
        if (chart.title && chart.title.text) {
            xml += '<c:title>';
            xml += '<c:tx><c:rich>';
            xml += '<a:bodyPr/><a:lstStyle/>';
            xml += '<a:p><a:pPr><a:defRPr/></a:pPr>';
            xml += `<a:r><a:rPr lang="en-US"/><a:t>${escapeXml(chart.title.text)}</a:t></a:r>`;
            xml += '</a:p></c:rich></c:tx>';
            xml += '<c:layout/><c:overlay val="0"/>';
            xml += '</c:title>';
            xml += '<c:autoTitleDeleted val="0"/>';
        } else {
            xml += '<c:autoTitleDeleted val="1"/>';
        }
        
        xml += '<c:plotArea>';
        xml += '<c:layout/>';
        
        // Scatter chart with line style
        const scatterStyle = chart.scatterStyle || 'line';
        xml += '<c:scatterChart>';
        xml += `<c:scatterStyle val="${scatterStyle}"/>`;
        xml += '<c:varyColors val="0"/>';
        
        // Generate series
        for (let i = 0; i < chart.series.length; i++) {
            xml += this._generateSeriesXML(chart.series[i], i, sheetName, dataInfo);
        }
        
        xml += `<c:axId val="${chart.xAxis.id}"/>`;
        xml += `<c:axId val="${chart.yAxis.id}"/>`;
        xml += '</c:scatterChart>';
        
        // X axis
        xml += this._generateAxisXML(chart.xAxis, 'b', chart.yAxis.id);
        
        // Y axis
        xml += this._generateAxisXML(chart.yAxis, 'l', chart.xAxis.id);
        
        xml += '</c:plotArea>';
        xml += '<c:legend><c:legendPos val="r"/><c:layout/><c:overlay val="0"/></c:legend>';
        xml += '<c:plotVisOnly val="1"/>';
        xml += '<c:dispBlanksAs val="gap"/>';
        xml += '<c:showDLblsOverMax val="0"/>';
        xml += '</c:chart>';
        
        // Chart styling - background color and border
        xml += '<c:spPr>';
        // Background fill - white by default, or custom color
        const bgColor = chart.backgroundColor || 'FFFFFF';
        xml += `<a:solidFill><a:srgbClr val="${bgColor}"/></a:solidFill>`;
        // Border - remove if showBorder is false
        if (chart.showBorder === false) {
            xml += '<a:ln><a:noFill/></a:ln>';
        }
        xml += '</c:spPr>';
        
        xml += '<c:printSettings><c:headerFooter/><c:pageMargins b="0.75" l="0.7" r="0.7" t="0.75" header="0.3" footer="0.3"/><c:pageSetup/></c:printSettings>';
        xml += '</c:chartSpace>';
        
        return xml;
    }
    
    /**
     * Generate series XML for scatter chart
     */
    _generateSeriesXML(series, index, sheetName, dataInfo) {
        let xml = '<c:ser>';
        xml += `<c:idx val="${index}"/>`;
        xml += `<c:order val="${index}"/>`;
        
        // Series name - reference header cell if dataInfo available
        if (series.name && series.name.text) {
            if (dataInfo) {
                // Reference header cell (row 1, column B for index 0, C for index 1, etc.)
                const headerCol = xlColumn(dataInfo.startCol + index + 1);
                const headerRow = dataInfo.startRow;
                xml += `<c:tx><c:strRef><c:f>${sheetName}!$${headerCol}$${headerRow}</c:f></c:strRef></c:tx>`;
            } else {
                xml += `<c:tx><c:v>${escapeXml(series.name.text)}</c:v></c:tx>`;
            }
        }
        
        // Line properties with color and dash type
        if (series.line && series.line.color && series.line.color.value) {
            const rgb = series.line.color.value;
            const hexColor = rgb.map(c => Math.round(c).toString(16).padStart(2, '0')).join('').toUpperCase();
            const lineWidth = (series.line.width || 2) * 12700; // EMUs
            const dashType = series.line.dashType || 'solid';
            xml += '<c:spPr>';
            xml += `<a:ln w="${lineWidth}">`;
            xml += `<a:solidFill><a:srgbClr val="${hexColor}"/></a:solidFill>`;
            xml += `<a:prstDash val="${dashType}"/>`;
            xml += '</a:ln>';
            xml += '</c:spPr>';
        }
        
        // No markers
        xml += '<c:marker><c:symbol val="none"/></c:marker>';
        
        // X values - use cell reference if dataInfo available
        if (dataInfo && dataInfo.numRows > 1) {
            const xCol = xlColumn(dataInfo.startCol);  // Column A = X values
            const startDataRow = dataInfo.startRow + 1;  // Skip header row
            const endDataRow = dataInfo.startRow + dataInfo.numRows;
            xml += '<c:xVal><c:numRef>';
            xml += `<c:f>${sheetName}!$${xCol}$${startDataRow}:$${xCol}$${endDataRow}</c:f>`;
            xml += '</c:numRef></c:xVal>';
        } else if (series.x && series.x.values && series.x.values.length > 0) {
            // Fallback to inline values
            xml += '<c:xVal><c:numLit>';
            xml += '<c:formatCode>General</c:formatCode>';
            xml += `<c:ptCount val="${series.x.values.length}"/>`;
            for (let j = 0; j < series.x.values.length; j++) {
                const val = series.x.values[j];
                if (val !== null && val !== undefined && !isNaN(val)) {
                    xml += `<c:pt idx="${j}"><c:v>${val}</c:v></c:pt>`;
                }
            }
            xml += '</c:numLit></c:xVal>';
        }
        
        // Y values - use cell reference if dataInfo available
        if (dataInfo && dataInfo.numRows > 1) {
            const yCol = xlColumn(dataInfo.startCol + index + 1);  // Column B, C, D... = Y values
            const startDataRow = dataInfo.startRow + 1;  // Skip header row
            const endDataRow = dataInfo.startRow + dataInfo.numRows;
            xml += '<c:yVal><c:numRef>';
            xml += `<c:f>${sheetName}!$${yCol}$${startDataRow}:$${yCol}$${endDataRow}</c:f>`;
            xml += '</c:numRef></c:yVal>';
        } else if (series.y && series.y.values && series.y.values.length > 0) {
            // Fallback to inline values
            xml += '<c:yVal><c:numLit>';
            xml += '<c:formatCode>General</c:formatCode>';
            xml += `<c:ptCount val="${series.y.values.length}"/>`;
            for (let j = 0; j < series.y.values.length; j++) {
                const val = series.y.values[j];
                if (val !== null && val !== undefined && !isNaN(val)) {
                    xml += `<c:pt idx="${j}"><c:v>${val}</c:v></c:pt>`;
                }
            }
            xml += '</c:numLit></c:yVal>';
        }
        
        xml += '<c:smooth val="0"/>';
        xml += '</c:ser>';
        return xml;
    }
    
    /**
     * Generate axis XML
     */
    _generateAxisXML(axis, position, crossAxisId) {
        const isLogScale = axis.logBase && !isNaN(axis.logBase) && axis.logBase > 1;
        
        let xml = '<c:valAx>';
        xml += `<c:axId val="${axis.id}"/>`;
        
        // Scaling with optional log scale and min/max
        xml += '<c:scaling>';
        if (isLogScale) {
            xml += `<c:logBase val="${axis.logBase}"/>`;
        }
        xml += '<c:orientation val="minMax"/>';
        if (axis.maximum !== undefined && !isNaN(axis.maximum)) {
            xml += `<c:max val="${axis.maximum}"/>`;
        }
        if (axis.minimum !== undefined && !isNaN(axis.minimum)) {
            xml += `<c:min val="${axis.minimum}"/>`;
        }
        xml += '</c:scaling>';
        
        xml += '<c:delete val="0"/>';
        xml += `<c:axPos val="${position}"/>`;
        
        // Major gridlines
        if (axis.majorGridlines !== false) {
            xml += '<c:majorGridlines>';
            if (axis.majorGridlines && (axis.majorGridlines.color || axis.majorGridlines.width)) {
                const color = axis.majorGridlines.color || 'D9D9D9';
                const width = Math.round((axis.majorGridlines.width || 0.75) * 12700);  // pt to EMUs
                xml += '<c:spPr>';
                xml += `<a:ln w="${width}">`;
                xml += `<a:solidFill><a:srgbClr val="${color}"/></a:solidFill>`;
                xml += '</a:ln>';
                xml += '</c:spPr>';
            }
            xml += '</c:majorGridlines>';
        }
        
        // Minor gridlines (configurable, useful for log scale)
        if (axis.minorGridlines) {
            xml += '<c:minorGridlines>';
            if (axis.minorGridlines.color || axis.minorGridlines.width) {
                const color = axis.minorGridlines.color || 'E5E5E5';
                const width = Math.round((axis.minorGridlines.width || 0.5) * 12700);  // pt to EMUs
                xml += '<c:spPr>';
                xml += `<a:ln w="${width}">`;
                xml += `<a:solidFill><a:srgbClr val="${color}"/></a:solidFill>`;
                xml += '</a:ln>';
                xml += '</c:spPr>';
            }
            xml += '</c:minorGridlines>';
        }
        
        // Axis title
        if (axis.title && axis.title.text) {
            xml += '<c:title>';
            xml += '<c:tx><c:rich>';
            xml += '<a:bodyPr/><a:lstStyle/>';
            xml += '<a:p><a:pPr><a:defRPr/></a:pPr>';
            xml += `<a:r><a:rPr lang="en-US"/><a:t>${escapeXml(axis.title.text)}</a:t></a:r>`;
            xml += '</a:p></c:rich></c:tx>';
            xml += '<c:layout/><c:overlay val="0"/>';
            xml += '</c:title>';
        }
        
        // Number format - use custom format if provided, otherwise General
        // Note: Only escape &, <, and " in attribute values (> doesn't need escaping in attributes)
        const numFmtCode = axis.numberFormat || axis.numberFormatCode || 'General';
        const escapedFmtCode = numFmtCode.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
        const sourceLinked = (axis.numberFormat || (axis.numberLinkedToSource === false)) ? '0' : '1';
        xml += `<c:numFmt formatCode="${escapedFmtCode}" sourceLinked="${sourceLinked}"/>`;
        xml += '<c:majorTickMark val="out"/>';
        const minorTickMark = axis.minorTickMark || 'none';
        xml += `<c:minorTickMark val="${minorTickMark}"/>`;
        xml += '<c:tickLblPos val="nextTo"/>';
        xml += `<c:crossAx val="${crossAxisId}"/>`;
        xml += '<c:crosses val="autoZero"/>';
        xml += '<c:crossBetween val="midCat"/>';
        xml += '</c:valAx>';
        return xml;
    }

    /**
     * Build and save the Excel file
     * @returns {Promise<Blob|Buffer>} The file as Blob (browser) or Buffer (Node.js)
     */
    async save() {
        // Reset charts array to avoid duplicates on multiple saves
        this.charts = [];
        
        // Add _rels/.rels
        this._addRels();
        
        // Add docProps
        this._addDocProps();
        
        // Add xl content (this populates this.charts)
        this._addXl();
        
        // Add [Content_Types].xml AFTER _addXl so charts are registered
        this._addContentTypes();
        
        // Generate the zip file
        const content = await this.zip.generateAsync({ 
            type: typeof window !== 'undefined' ? 'blob' : 'nodebuffer',
            compression: 'DEFLATE',
            compressionOptions: { level: 6 }
        });
        
        return content;
    }
    
    /**
     * Save to file (Node.js) or trigger download (browser)
     */
    async saveAs(filename) {
        const content = await this.save();
        filename = filename || this.filename;
        
        if (typeof window !== 'undefined') {
            // Browser: trigger download
            const url = URL.createObjectURL(content);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } else if (typeof require !== 'undefined') {
            // Node.js: write to file
            const fs = require('fs');
            fs.writeFileSync(filename, content);
        }
        
        return content;
    }
    
    /**
     * Add [Content_Types].xml
     */
    _addContentTypes() {
        let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        xml += '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">';
        xml += '<Default Extension="png" ContentType="image/png"/>';
        xml += '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>';
        xml += '<Default Extension="xml" ContentType="application/xml"/>';
        xml += '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>';
        xml += '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>';
        xml += '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>';
        xml += '<Override PartName="/xl/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>';
        xml += '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>';
        xml += '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>';
        
        // Add worksheet content types
        for (let i = 0; i < this.sheets.length; i++) {
            xml += `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`;
        }
        
        // Add chart content types
        for (let i = 0; i < this.charts.length; i++) {
            xml += `<Override PartName="/xl/charts/chart${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>`;
            xml += `<Override PartName="/xl/drawings/drawing${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>`;
        }
        
        xml += '</Types>';
        this.zip.file('[Content_Types].xml', xml);
    }
    
    /**
     * Add _rels/.rels
     */
    _addRels() {
        let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        xml += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">';
        xml += '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>';
        xml += '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>';
        xml += '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>';
        xml += '</Relationships>';
        this.zip.file('_rels/.rels', xml);
    }
    
    /**
     * Add docProps
     */
    _addDocProps() {
        const date = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
        const username = typeof process !== 'undefined' && process.env ? (process.env.USERNAME || process.env.USER || 'User') : 'User';
        
        // app.xml
        let appXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        appXml += '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">';
        appXml += '<Application>xlsxwrite.js</Application>';
        appXml += '<DocSecurity>0</DocSecurity>';
        appXml += '<ScaleCrop>false</ScaleCrop>';
        appXml += '<HeadingPairs><vt:vector size="2" baseType="variant">';
        appXml += '<vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>';
        appXml += `<vt:variant><vt:i4>${this.sheets.length}</vt:i4></vt:variant>`;
        appXml += '</vt:vector></HeadingPairs>';
        appXml += '<TitlesOfParts><vt:vector size="' + this.sheets.length + '" baseType="lpstr">';
        for (const sheet of this.sheets) {
            appXml += `<vt:lpstr>${escapeXml(sheet.name)}</vt:lpstr>`;
        }
        appXml += '</vt:vector></TitlesOfParts>';
        appXml += '<Company></Company>';
        appXml += '<LinksUpToDate>false</LinksUpToDate>';
        appXml += '<SharedDoc>false</SharedDoc>';
        appXml += '<HyperlinksChanged>false</HyperlinksChanged>';
        appXml += '<AppVersion>12.0000</AppVersion>';
        appXml += '</Properties>';
        this.zip.file('docProps/app.xml', appXml);
        
        // core.xml
        let coreXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        coreXml += '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" ';
        coreXml += 'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" ';
        coreXml += 'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">';
        coreXml += `<dc:creator>${escapeXml(username)}</dc:creator>`;
        coreXml += `<cp:lastModifiedBy>${escapeXml(username)}</cp:lastModifiedBy>`;
        coreXml += `<dcterms:created xsi:type="dcterms:W3CDTF">${date}</dcterms:created>`;
        coreXml += `<dcterms:modified xsi:type="dcterms:W3CDTF">${date}</dcterms:modified>`;
        coreXml += '</cp:coreProperties>';
        this.zip.file('docProps/core.xml', coreXml);
    }
    
    /**
     * Add xl folder content
     */
    _addXl() {
        // styles.xml
        this._addStyles();
        
        // theme/theme1.xml
        this._addTheme();
        
        // workbook.xml
        this._addWorkbook();
        
        // workbook.xml.rels
        this._addWorkbookRels();
        
        // sharedStrings.xml
        this._addSharedStrings();
        
        // worksheets
        this._addWorksheets();
        
        // charts (if any)
        this._addCharts();
    }
    
    /**
     * Add styles.xml
     */
    _addStyles() {
        let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        xml += '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">';
        xml += '<fonts count="1"><font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/><scheme val="minor"/></font></fonts>';
        xml += '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>';
        xml += '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>';
        xml += '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>';
        xml += '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>';
        xml += '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>';
        xml += '<dxfs count="0"/>';
        xml += '<tableStyles count="0" defaultTableStyle="TableStyleMedium9" defaultPivotStyle="PivotStyleLight16"/>';
        xml += '</styleSheet>';
        this.zip.file('xl/styles.xml', xml);
    }
    
    /**
     * Add theme1.xml (minimal theme)
     */
    _addTheme() {
        let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        xml += '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office Theme">';
        xml += '<a:themeElements>';
        xml += '<a:clrScheme name="Office">';
        xml += '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>';
        xml += '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>';
        xml += '<a:dk2><a:srgbClr val="1F497D"/></a:dk2>';
        xml += '<a:lt2><a:srgbClr val="EEECE1"/></a:lt2>';
        xml += '<a:accent1><a:srgbClr val="4F81BD"/></a:accent1>';
        xml += '<a:accent2><a:srgbClr val="C0504D"/></a:accent2>';
        xml += '<a:accent3><a:srgbClr val="9BBB59"/></a:accent3>';
        xml += '<a:accent4><a:srgbClr val="8064A2"/></a:accent4>';
        xml += '<a:accent5><a:srgbClr val="4BACC6"/></a:accent5>';
        xml += '<a:accent6><a:srgbClr val="F79646"/></a:accent6>';
        xml += '<a:hlink><a:srgbClr val="0000FF"/></a:hlink>';
        xml += '<a:folHlink><a:srgbClr val="800080"/></a:folHlink>';
        xml += '</a:clrScheme>';
        xml += '<a:fontScheme name="Office">';
        xml += '<a:majorFont><a:latin typeface="Cambria"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>';
        xml += '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>';
        xml += '</a:fontScheme>';
        xml += '<a:fmtScheme name="Office">';
        xml += '<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>';
        xml += '<a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>';
        xml += '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>';
        xml += '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>';
        xml += '</a:fmtScheme>';
        xml += '</a:themeElements>';
        xml += '<a:objectDefaults/><a:extraClrSchemeLst/>';
        xml += '</a:theme>';
        this.zip.file('xl/theme/theme1.xml', xml);
    }
    
    /**
     * Add workbook.xml
     */
    _addWorkbook() {
        let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        xml += '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ';
        xml += 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">';
        xml += '<fileVersion appName="xl" lastEdited="4" lowestEdited="4" rupBuild="4505"/>';
        xml += '<workbookPr defaultThemeVersion="124226"/>';
        xml += '<bookViews><workbookView activeTab="0" xWindow="240" yWindow="15" windowWidth="16095" windowHeight="9660"/></bookViews>';
        xml += '<sheets>';
        
        for (let i = 0; i < this.sheets.length; i++) {
            xml += `<sheet name="${escapeXml(this.sheets[i].name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`;
        }
        
        xml += '</sheets>';
        xml += '<calcPr calcId="124519" fullCalcOnLoad="1"/>';
        xml += '</workbook>';
        this.zip.file('xl/workbook.xml', xml);
    }
    
    /**
     * Add workbook.xml.rels
     */
    _addWorkbookRels() {
        let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        xml += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">';
        
        // Worksheet relationships
        for (let i = 0; i < this.sheets.length; i++) {
            xml += `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`;
        }
        
        // Other relationships
        const baseId = this.sheets.length;
        xml += `<Relationship Id="rId${baseId + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>`;
        xml += `<Relationship Id="rId${baseId + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`;
        xml += `<Relationship Id="rId${baseId + 3}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>`;
        
        xml += '</Relationships>';
        this.zip.file('xl/_rels/workbook.xml.rels', xml);
    }
    
    /**
     * Add sharedStrings.xml
     */
    _addSharedStrings() {
        let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
        xml += `<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" uniqueCount="${this.sharedStrings.length}">`;
        
        for (const str of this.sharedStrings) {
            xml += `<si><t>${escapeXml(str)}</t></si>`;
        }
        
        xml += '</sst>';
        this.zip.file('xl/sharedStrings.xml', xml);
    }
    
    /**
     * Add worksheets
     */
    _addWorksheets() {
        for (let i = 0; i < this.sheets.length; i++) {
            const sheet = this.sheets[i];
            
            let xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
            xml += '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ';
            xml += 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">';
            xml += '<sheetViews><sheetView workbookViewId="0"/></sheetViews>';
            xml += '<sheetFormatPr defaultRowHeight="15"/>';
            xml += '<sheetData>';
            xml += this._generateSheetDataXML(sheet);
            xml += '</sheetData>';
            xml += '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>';
            
            // Add drawing reference if there's a chart (after pageMargins per OOXML schema)
            if (sheet.chart) {
                this.charts.push({ 
                    chart: sheet.chart, 
                    sheetIndex: i, 
                    sheetName: sheet.name,
                    dataInfo: {
                        startRow: sheet.startRow,
                        startCol: sheet.startCol,
                        numRows: sheet.data.length,
                        numCols: sheet.data.length > 0 ? sheet.data[0].length : 0
                    }
                });
                xml += `<drawing r:id="rId1"/>`;
            }
            
            xml += '</worksheet>';
            this.zip.file(`xl/worksheets/sheet${i + 1}.xml`, xml);
            
            // Add sheet rels if there's a chart
            if (sheet.chart) {
                let relsXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
                relsXml += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">';
                relsXml += `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing${this.charts.length}.xml"/>`;
                relsXml += '</Relationships>';
                this.zip.file(`xl/worksheets/_rels/sheet${i + 1}.xml.rels`, relsXml);
            }
        }
    }
    
    /**
     * Add charts
     */
    _addCharts() {
        for (let i = 0; i < this.charts.length; i++) {
            const chartInfo = this.charts[i];
            const chartId = i + 1;
            
            // chart.xml
            const chartXml = this._generateChartXML(chartInfo.chart, chartInfo.sheetName, chartInfo.dataInfo);
            this.zip.file(`xl/charts/chart${chartId}.xml`, chartXml);
            
            // Calculate cell positions for chart placement
            const startCol = Math.floor(chartInfo.chart.x / 64) || 2;
            const startRow = Math.floor(chartInfo.chart.y / 20) || 1;
            const endCol = startCol + Math.ceil((chartInfo.chart.width || 480) / 64);
            const endRow = startRow + Math.ceil((chartInfo.chart.height || 288) / 20);
            
            // drawing.xml - exact xlsxwriter format
            let drawingXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
            drawingXml += '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">';
            drawingXml += '<xdr:twoCellAnchor>';
            drawingXml += '<xdr:from>';
            drawingXml += `<xdr:col>${startCol}</xdr:col>`;
            drawingXml += '<xdr:colOff>0</xdr:colOff>';
            drawingXml += `<xdr:row>${startRow}</xdr:row>`;
            drawingXml += '<xdr:rowOff>0</xdr:rowOff>';
            drawingXml += '</xdr:from>';
            drawingXml += '<xdr:to>';
            drawingXml += `<xdr:col>${endCol}</xdr:col>`;
            drawingXml += '<xdr:colOff>0</xdr:colOff>';
            drawingXml += `<xdr:row>${endRow}</xdr:row>`;
            drawingXml += '<xdr:rowOff>0</xdr:rowOff>';
            drawingXml += '</xdr:to>';
            drawingXml += '<xdr:graphicFrame macro="">';
            drawingXml += '<xdr:nvGraphicFramePr>';
            drawingXml += `<xdr:cNvPr id="${chartId + 1}" name="Chart ${chartId}"/>`;
            drawingXml += '<xdr:cNvGraphicFramePr/>';
            drawingXml += '</xdr:nvGraphicFramePr>';
            drawingXml += '<xdr:xfrm>';
            drawingXml += '<a:off x="0" y="0"/>';
            drawingXml += '<a:ext cx="0" cy="0"/>';
            drawingXml += '</xdr:xfrm>';
            drawingXml += '<a:graphic>';
            drawingXml += '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">';
            drawingXml += '<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/>';
            drawingXml += '</a:graphicData>';
            drawingXml += '</a:graphic>';
            drawingXml += '</xdr:graphicFrame>';
            drawingXml += '<xdr:clientData/>';
            drawingXml += '</xdr:twoCellAnchor>';
            drawingXml += '</xdr:wsDr>';
            this.zip.file(`xl/drawings/drawing${chartId}.xml`, drawingXml);
            
            // drawing rels
            let drawingRelsXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
            drawingRelsXml += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">';
            drawingRelsXml += `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart${chartId}.xml"/>`;
            drawingRelsXml += '</Relationships>';
            this.zip.file(`xl/drawings/_rels/drawing${chartId}.xml.rels`, drawingRelsXml);
        }
    }
}

// ============================================================================
// Exports
// ============================================================================

// Export for different environments
if (typeof module !== 'undefined' && module.exports) {
    // Node.js
    module.exports = {
        XlsxWriter,
        xlColumn,
        xlCell2Ind,
        getHexColor,
        getDefaultChart,
        getDefaultSeries,
        getDefaultAxis,
        getDefaultLine,
        getDefaultFont,
        getDefaultColor,
        getDefaultMarker,
        getDefaultLabel,
        getDefaultComment,
        getDefaultTextBox,
        NAMED_COLORS,
        DASH_TYPES
    };
} else if (typeof window !== 'undefined') {
    // Browser
    window.XlsxWriter = XlsxWriter;
    window.xlsxwrite = {
        XlsxWriter,
        xlColumn,
        xlCell2Ind,
        getHexColor,
        getDefaultChart,
        getDefaultSeries,
        getDefaultAxis,
        getDefaultLine,
        getDefaultFont,
        getDefaultColor,
        getDefaultMarker,
        getDefaultLabel,
        getDefaultComment,
        getDefaultTextBox,
        NAMED_COLORS,
        DASH_TYPES
    };
}
