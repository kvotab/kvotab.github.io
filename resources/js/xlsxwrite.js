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

// ============================================================================
// Constants
// ============================================================================

/** Conversion factor: points to EMUs (English Metric Units) */
const PT_TO_EMU = 12700;

/** Conversion factor: inches to EMUs */
const INCH_TO_EMU = 914400;

/** Default chart dimensions */
const DEFAULT_CHART_DIM = {
    WIDTH: 480,
    HEIGHT: 288,
    COL_WIDTH_PX: 64,
    ROW_HEIGHT_PX: 20
};

/** Default font settings */
const DEFAULT_FONT = {
    NAME: 'Calibri',
    SIZE: 11,
    FAMILY: 2
};

/** Custom number format starting index (per OOXML spec) */
const CUSTOM_NUM_FMT_START_ID = 164;

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
 * Marker types available in Excel charts
 */
const MARKER_TYPES = {
    'automatic': 'auto',
    'none': 'none',
    'circle': 'circle',
    'diamond': 'diamond',
    'square': 'square',
    'triangle': 'triangle',
    'x': 'x',
    'star': 'star',
    'plus': 'plus',
    'dot': 'dot',
    'dash': 'dash',
    'short_dash': 'dash',
    'long_dash': 'dash',
    'picture': 'picture'
};

/**
 * Built-in number format codes
 */
const NUM_FORMATS = {
    'General': 0,
    '0': 1,
    '0.00': 2,
    '#,##0': 3,
    '#,##0.00': 4,
    '0%': 9,
    '0.00%': 10,
    '0.00E+00': 11,
    '# ?/?': 12,
    '# ??/??': 13,
    'mm-dd-yy': 14,
    'd-mmm-yy': 15,
    'd-mmm': 16,
    'mmm-yy': 17,
    'h:mm AM/PM': 18,
    'h:mm:ss AM/PM': 19,
    'h:mm': 20,
    'h:mm:ss': 21,
    'm/d/yy h:mm': 22,
    '#,##0 ;(#,##0)': 37,
    '#,##0 ;[Red](#,##0)': 38,
    '#,##0.00;(#,##0.00)': 39,
    '#,##0.00;[Red](#,##0.00)': 40,
    'mm:ss': 45,
    '[h]:mm:ss': 46,
    'mmss.0': 47,
    '##0.0E+0': 48,
    '@': 49
};

/**
 * Border style mapping
 */
const BORDER_STYLES = {
    'none': null,
    'thin': 'thin',
    'medium': 'medium',
    'dashed': 'dashed',
    'dotted': 'dotted',
    'thick': 'thick',
    'double': 'double',
    'hair': 'hair',
    'mediumDashed': 'mediumDashed',
    'dashDot': 'dashDot',
    'mediumDashDot': 'mediumDashDot',
    'dashDotDot': 'dashDotDot',
    'mediumDashDotDot': 'mediumDashDotDot',
    'slantDashDot': 'slantDashDot'
};

/**
 * Pattern fill types
 */
const PATTERN_TYPES = {
    'none': 'none',
    'solid': 'solid',
    'gray125': 'gray125',
    'gray0625': 'gray0625',
    'darkGray': 'darkGray',
    'mediumGray': 'mediumGray',
    'lightGray': 'lightGray',
    'darkHorizontal': 'darkHorizontal',
    'darkVertical': 'darkVertical',
    'darkDown': 'darkDown',
    'darkUp': 'darkUp',
    'darkGrid': 'darkGrid',
    'darkTrellis': 'darkTrellis',
    'lightHorizontal': 'lightHorizontal',
    'lightVertical': 'lightVertical',
    'lightDown': 'lightDown',
    'lightUp': 'lightUp',
    'lightGrid': 'lightGrid',
    'lightTrellis': 'lightTrellis'
};

/** Cache for column letter lookups (A-ZZ = 702 columns) */
const XL_COLUMN_CACHE = {};

/**
 * Convert column number to Excel column letter(s)
 * @param {number} column - 1-based column number
 * @returns {string} Column letter(s) (A, B, ..., Z, AA, AB, ...)
 */
function xlColumn(column) {
    // Return cached value if available
    if (XL_COLUMN_CACHE[column]) return XL_COLUMN_CACHE[column];
    
    let result = '';
    let col = column;
    while (col > 0) {
        col--;
        result = String.fromCharCode(65 + (col % 26)) + result;
        col = Math.floor(col / 26);
    }
    
    // Cache columns up to ZZ (702) to avoid unbounded growth
    if (column <= 702) XL_COLUMN_CACHE[column] = result;
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

/** XML escape character map for single-pass replacement */
const XML_ESCAPE_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };
const XML_ESCAPE_RE = /[&<>"']/g;

/**
 * Escape XML special characters (single-pass for performance)
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
function escapeXml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(XML_ESCAPE_RE, c => XML_ESCAPE_MAP[c]);
}

/** XML attribute escape for single-pass replacement */
const XML_ATTR_ESCAPE_MAP = { '&': '&amp;', '<': '&lt;', '"': '&quot;' };
const XML_ATTR_ESCAPE_RE = /[&<"]/g;

/**
 * Escape string for XML attribute values (single-pass for performance)
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
function escapeXmlAttr(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(XML_ATTR_ESCAPE_RE, c => XML_ATTR_ESCAPE_MAP[c]);
}

/**
 * Convert RGB array or color value to 6-digit hex string
 * @param {number[]|string|number} color - RGB array [r,g,b], hex string, or color value
 * @returns {string} 6-digit uppercase hex color string
 */
function toHexColor(color) {
    if (Array.isArray(color)) {
        return color.map(c => Math.round(c).toString(16).padStart(2, '0')).join('').toUpperCase();
    }
    if (typeof color === 'string') {
        return color.replace(/^#/, '').toUpperCase();
    }
    return getHexColor(color);
}

/**
 * Escape sheet name for use in Excel formulas
 * Sheet names with special characters must be quoted
 * @param {string} name - Sheet name
 * @returns {string} Escaped sheet name safe for formula references
 */
function escapeSheetName(name) {
    if (!name) return 'Sheet1';
    // Sheet names with spaces, special chars, or starting with digits need quotes
    if (/[^A-Za-z0-9_]/.test(name) || /^\d/.test(name)) {
        // Escape single quotes by doubling them, then wrap in quotes
        return "'" + name.replace(/'/g, "''") + "'";
    }
    return name;
}

/**
 * Generate unique ID
 * @returns {number} Random ID
 */
function generateId() {
    return Math.floor(Math.random() * 1e9);
}

// ============================================================================
// Format Class for Cell Formatting
// ============================================================================

/**
 * Format class for cell formatting (similar to XlsxWriter's Format)
 */
class Format {
    constructor(properties = {}) {
        // Font properties
        this.fontName = properties.font_name || properties.fontName || 'Calibri';
        this.fontSize = properties.font_size || properties.fontSize || 11;
        this.fontColor = properties.font_color || properties.fontColor || null;
        this.bold = properties.bold || false;
        this.italic = properties.italic || false;
        this.underline = properties.underline || 0;  // 0, 1 (single), 2 (double)
        this.fontStrikeout = properties.font_strikeout || properties.fontStrikeout || false;
        this.fontScript = properties.font_script || properties.fontScript || 0;  // 0=normal, 1=superscript, 2=subscript
        
        // Number format
        this.numFormat = properties.num_format || properties.numFormat || 'General';
        this.numFormatIndex = properties.num_format_index || properties.numFormatIndex || 0;
        
        // Alignment
        this.align = properties.align || null;  // left, center, right, fill, justify, center_across, distributed
        this.valign = properties.valign || null;  // top, vcenter, bottom, vjustify, vdistributed
        this.rotation = properties.rotation || 0;
        this.textWrap = properties.text_wrap || properties.textWrap || false;
        this.shrink = properties.shrink || false;
        this.indent = properties.indent || 0;
        
        // Border
        this.border = properties.border || 0;
        this.borderColor = properties.border_color || properties.borderColor || null;
        this.left = properties.left || 0;
        this.leftColor = properties.left_color || properties.leftColor || null;
        this.right = properties.right || 0;
        this.rightColor = properties.right_color || properties.rightColor || null;
        this.top = properties.top || 0;
        this.topColor = properties.top_color || properties.topColor || null;
        this.bottom = properties.bottom || 0;
        this.bottomColor = properties.bottom_color || properties.bottomColor || null;
        this.diagonalType = properties.diagonal_type || properties.diagonalType || 0;
        this.diagonalBorder = properties.diagonal_border || properties.diagonalBorder || 0;
        this.diagonalColor = properties.diagonal_color || properties.diagonalColor || null;
        
        // Fill
        this.pattern = properties.pattern || 0;  // 0=none, 1=solid, etc.
        this.bgColor = properties.bg_color || properties.bgColor || null;
        this.fgColor = properties.fg_color || properties.fgColor || null;
        
        // Protection
        this.locked = properties.locked !== undefined ? properties.locked : true;
        this.hidden = properties.hidden || false;
        
        // Internal indices (set by workbook)
        this.xfIndex = null;
        this.fontIndex = null;
        this.fillIndex = null;
        this.borderIndex = null;
        
        // Apply border shorthand
        if (this.border) {
            this.left = this.left || this.border;
            this.right = this.right || this.border;
            this.top = this.top || this.border;
            this.bottom = this.bottom || this.border;
        }
        if (this.borderColor) {
            this.leftColor = this.leftColor || this.borderColor;
            this.rightColor = this.rightColor || this.borderColor;
            this.topColor = this.topColor || this.borderColor;
            this.bottomColor = this.bottomColor || this.borderColor;
        }
    }
    
    // Setter methods for chaining (snake_case like Python XlsxWriter)
    // Each setter invalidates the cached key to ensure getKey() returns correct value
    set_font_name(name) { this.fontName = name; this._cachedKey = undefined; return this; }
    set_font_size(size) { this.fontSize = size; this._cachedKey = undefined; return this; }
    set_font_color(color) { this.fontColor = color; this._cachedKey = undefined; return this; }
    set_bold(bold = true) { this.bold = bold; this._cachedKey = undefined; return this; }
    set_italic(italic = true) { this.italic = italic; this._cachedKey = undefined; return this; }
    set_underline(style = 1) { this.underline = style; this._cachedKey = undefined; return this; }
    set_font_strikeout(strikeout = true) { this.fontStrikeout = strikeout; this._cachedKey = undefined; return this; }
    set_font_script(script) { this.fontScript = script; this._cachedKey = undefined; return this; }
    set_num_format(format) { this.numFormat = format; this._cachedKey = undefined; return this; }
    set_align(align) { this.align = align; this._cachedKey = undefined; return this; }
    set_valign(valign) { this.valign = valign; this._cachedKey = undefined; return this; }
    set_rotation(angle) { this.rotation = angle; this._cachedKey = undefined; return this; }
    set_text_wrap(wrap = true) { this.textWrap = wrap; this._cachedKey = undefined; return this; }
    set_shrink(shrink = true) { this.shrink = shrink; this._cachedKey = undefined; return this; }
    set_indent(indent) { this.indent = indent; this._cachedKey = undefined; return this; }
    set_border(style) { 
        this.left = this.right = this.top = this.bottom = style;
        this._cachedKey = undefined;
        return this; 
    }
    set_border_color(color) {
        this.leftColor = this.rightColor = this.topColor = this.bottomColor = color;
        this._cachedKey = undefined;
        return this;
    }
    set_left(style) { this.left = style; this._cachedKey = undefined; return this; }
    set_right(style) { this.right = style; this._cachedKey = undefined; return this; }
    set_top(style) { this.top = style; this._cachedKey = undefined; return this; }
    set_bottom(style) { this.bottom = style; this._cachedKey = undefined; return this; }
    set_left_color(color) { this.leftColor = color; this._cachedKey = undefined; return this; }
    set_right_color(color) { this.rightColor = color; this._cachedKey = undefined; return this; }
    set_top_color(color) { this.topColor = color; this._cachedKey = undefined; return this; }
    set_bottom_color(color) { this.bottomColor = color; this._cachedKey = undefined; return this; }
    set_pattern(pattern) { this.pattern = pattern; this._cachedKey = undefined; return this; }
    set_bg_color(color) { this.bgColor = color; if (!this.pattern) this.pattern = 1; this._cachedKey = undefined; return this; }
    set_fg_color(color) { this.fgColor = color; if (!this.pattern) this.pattern = 1; this._cachedKey = undefined; return this; }
    set_locked(locked = true) { this.locked = locked; this._cachedKey = undefined; return this; }
    set_hidden(hidden = true) { this.hidden = hidden; this._cachedKey = undefined; return this; }
    
    // CamelCase aliases for JavaScript convention
    setFontName(name) { return this.set_font_name(name); }
    setFontSize(size) { return this.set_font_size(size); }
    setFontColor(color) { return this.set_font_color(color); }
    setBold(bold = true) { return this.set_bold(bold); }
    setItalic(italic = true) { return this.set_italic(italic); }
    setUnderline(style = 1) { return this.set_underline(style); }
    setFontStrikeout(strikeout = true) { return this.set_font_strikeout(strikeout); }
    setFontScript(script) { return this.set_font_script(script); }
    setNumFormat(format) { return this.set_num_format(format); }
    setAlign(align) { return this.set_align(align); }
    setValign(valign) { return this.set_valign(valign); }
    setRotation(angle) { return this.set_rotation(angle); }
    setTextWrap(wrap = true) { return this.set_text_wrap(wrap); }
    setShrink(shrink = true) { return this.set_shrink(shrink); }
    setIndent(indent) { return this.set_indent(indent); }
    setBorder(style) { return this.set_border(style); }
    setBorderColor(color) { return this.set_border_color(color); }
    setLeft(style) { return this.set_left(style); }
    setRight(style) { return this.set_right(style); }
    setTop(style) { return this.set_top(style); }
    setBottom(style) { return this.set_bottom(style); }
    setLeftColor(color) { return this.set_left_color(color); }
    setRightColor(color) { return this.set_right_color(color); }
    setTopColor(color) { return this.set_top_color(color); }
    setBottomColor(color) { return this.set_bottom_color(color); }
    setPattern(pattern) { return this.set_pattern(pattern); }
    setBgColor(color) { return this.set_bg_color(color); }
    setFgColor(color) { return this.set_fg_color(color); }
    setLocked(locked = true) { return this.set_locked(locked); }
    setHidden(hidden = true) { return this.set_hidden(hidden); }
    
    /**
     * Get a unique key for this format (for deduplication)
     * Cached after first computation for O(1) subsequent calls
     */
    getKey() {
        if (this._cachedKey === undefined) {
            this._cachedKey = JSON.stringify({
                fn: this.fontName, fs: this.fontSize, fc: this.fontColor,
                b: this.bold, i: this.italic, u: this.underline, st: this.fontStrikeout, sc: this.fontScript,
                nf: this.numFormat,
                al: this.align, va: this.valign, r: this.rotation, tw: this.textWrap, sh: this.shrink, in: this.indent,
                l: this.left, lc: this.leftColor, ri: this.right, rc: this.rightColor,
                t: this.top, tc: this.topColor, bo: this.bottom, bc: this.bottomColor,
                p: this.pattern, bg: this.bgColor, fg: this.fgColor,
                lo: this.locked, hi: this.hidden
            });
        }
        return this._cachedKey;
    }
    
    /**
     * Invalidate cached key (call after modifying properties)
     * @private
     */
    _invalidateCache() {
        this._cachedKey = undefined;
    }
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
        // SECURITY: Prevent prototype pollution attacks
        if (key === '__proto__' || key === 'constructor' || key === 'prototype') {
            continue;
        }
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
        type: 'scatter',  // 'scatter', 'line', 'area', 'bar', 'column', 'pie', 'doughnut', 'radar'
        option: 'PrimaryAxis',  // 'PrimaryAxis', 'SecondaryAxis'
        order: NaN,
        name: { ref: '', text: '' },
        x: { ref: '', values: [] },
        y: { ref: '', values: [] },
        length: 0,
        line: getDefaultLine({ width: 1.5, color: getDefaultColor({ option: 'Solid' }) }),
        marker: getDefaultMarker(),
        smooth: false,  // Smooth line for scatter/line charts
        legendVisible: true,
        label: getDefaultLabel(),
        dataLabels: null,  // Data labels configuration
        trendline: null,   // Trendline configuration
        errorBars: null    // Error bars configuration
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
        type: 'scatter',       // 'scatter', 'line', 'area', 'bar', 'column', 'pie', 'doughnut', 'radar'
        subtype: null,         // 'straight', 'straight_with_markers', 'smooth', 'smooth_with_markers', 'stacked', 'percent_stacked'
        scatterStyle: 'lineMarker',
        grouping: 'standard',  // 'standard', 'stacked', 'percentStacked'
        barDir: 'col',         // 'col' for column, 'bar' for bar
        gapWidth: 150,
        overlap: 0,
        height: 288,
        width: 480,
        x: 0,
        y: 0,
        title: getDefaultTitle({ font: getDefaultFont({ size: 14 }) }),
        xAxis: getDefaultAxis(),
        yAxis: getDefaultAxis({ title: { customAngle: -90 } }),
        x2Axis: getDefaultAxis({ visible: false }),
        y2Axis: getDefaultAxis({ visible: false, title: { customAngle: -90 } }),
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
        series: [],
        showBorder: true,
        backgroundColor: 'FFFFFF',
        style: 2  // Excel chart style (1-48)
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
        this.sheetMap = new Map();  // Sheet name -> index for O(1) lookup
        this.sharedStrings = [];
        this.sharedStringsMap = new Map();  // String -> index for O(1) lookup
        this.charts = [];
        this.comments = [];
        this.currentSheetId = 0;
        
        // Format management
        this.formats = [];
        this.formatMap = new Map();  // Key -> Format index
        this.customNumFormats = new Map();  // Custom number format -> id
        this.nextNumFormatId = 164;  // Custom formats start at 164
        
        // Add default format
        this._defaultFormat = this.addFormat({});
        
        // Column/row dimensions
        this.columnInfo = {};  // { sheetIndex: { col: { width, format, hidden } } }
        this.rowInfo = {};     // { sheetIndex: { row: { height, format, hidden } } }
        
        // Merge cells
        this.mergeCells = {};  // { sheetIndex: [ { start, end } ] }
        
        // Images
        this.images = [];      // { sheetIndex, filename, data, row, col, options }
    }
    
    /**
     * Add a format for cell styling
     * @param {Object} properties - Format properties
     * @returns {Format} Format object
     */
    addFormat(properties = {}) {
        const format = new Format(properties);
        const key = format.getKey();
        
        if (this.formatMap.has(key)) {
            return this.formats[this.formatMap.get(key)];
        }
        
        format.xfIndex = this.formats.length;
        this.formats.push(format);
        this.formatMap.set(key, format.xfIndex);
        
        // Handle custom number format
        if (format.numFormat && format.numFormat !== 'General') {
            if (NUM_FORMATS[format.numFormat] !== undefined) {
                format.numFormatIndex = NUM_FORMATS[format.numFormat];
            } else if (!this.customNumFormats.has(format.numFormat)) {
                this.customNumFormats.set(format.numFormat, this.nextNumFormatId);
                format.numFormatIndex = this.nextNumFormatId;
                this.nextNumFormatId++;
            } else {
                format.numFormatIndex = this.customNumFormats.get(format.numFormat);
            }
        }
        
        return format;
    }
    
    /**
     * Create a new chart configuration
     * @param {Object} options - Chart options including type
     * @returns {Object} Chart configuration object
     */
    newChart(typeOrOptions = {}, subtype = null) {
        // Support both newChart('line') and newChart({ type: 'line' })
        let options = typeOrOptions;
        if (typeof typeOrOptions === 'string') {
            options = { type: typeOrOptions, subtype };
        }
        
        const chartType = options.type || 'scatter';
        const chartSubtype = options.subtype || subtype || null;
        
        // Set scatterStyle based on type and subtype
        let scatterStyle = 'lineMarker';
        if (chartType === 'scatter') {
            if (chartSubtype === 'straight') scatterStyle = 'lineMarker';
            else if (chartSubtype === 'straight_with_markers') scatterStyle = 'lineMarker';
            else if (chartSubtype === 'smooth') scatterStyle = 'smoothMarker';
            else if (chartSubtype === 'smooth_with_markers') scatterStyle = 'smoothMarker';
            else if (chartSubtype === 'markers_only' || chartSubtype === 'lineMarkers') scatterStyle = 'lineMarker';
            else scatterStyle = 'lineMarker';
        }
        
        return getDefaultChart({ 
            type: chartType, 
            subtype: chartSubtype,
            scatterStyle,
            ...options 
        });
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
        // Determine marker settings based on chart subtype
        let markerOption = options.marker?.option || 'NoMarker';
        let showMarkers = options.showMarkers;
        
        if (showMarkers === undefined) {
            // Auto-determine based on subtype
            const subtype = chart.subtype || '';
            if (subtype.includes('markers') || subtype === 'markers_only') {
                showMarkers = true;
            } else if (chart.type === 'scatter' && !subtype) {
                // Default scatter with no subtype shows markers only (no lines)
                showMarkers = true;
            }
        }
        
        if (showMarkers) {
            markerOption = 'Built-in';
        }
        
        // Handle line visibility based on subtype
        let lineConfig = options.line || getDefaultLine({
            color: getDefaultColor({ option: 'Solid', value: options.color || this._getDefaultSeriesColor(chart.series.length) })
        });
        
        // For markers_only subtype, hide the line
        if (chart.subtype === 'markers_only') {
            lineConfig = { ...lineConfig, color: { ...lineConfig.color, option: 'None' } };
        }
        
        const series = this.newSeries({
            name: { text: options.name || `Series${chart.series.length + 1}` },
            x: { values: options.xValues || [], ref: options.xRef || '' },
            y: { values: options.yValues || [], ref: options.yRef || '' },
            length: options.yValues ? options.yValues.length : 0,
            line: lineConfig,
            marker: options.marker || getDefaultMarker({ 
                option: markerOption,
                type: options.markerType || 'circle',
                size: options.markerSize || 5
            }),
            smooth: options.smooth || (chart.subtype?.includes('smooth') ? true : false),
            dataLabels: options.dataLabels || null,
            trendline: options.trendline || null
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
     * Get or create sheet by name/index
     * Uses Map for O(1) lookup instead of O(n) array search
     * @private
     */
    _getOrCreateSheet(sheet) {
        const sheetName = typeof sheet === 'number' ? `Sheet${sheet}` : sheet;
        let sheetIndex = this.sheetMap.get(sheetName);
        
        if (sheetIndex === undefined) {
            sheetIndex = this.sheets.length;
            this.sheets.push({
                name: sheetName,
                data: [],
                startRow: 1,
                startCol: 1,
                chart: null,
                comments: []
            });
            this.sheetMap.set(sheetName, sheetIndex);
        }
        
        return { sheetIndex, sheetName };
    }
    
    /**
     * Write a single cell value
     * @param {number|string} row - Row number (0-indexed) or cell reference ('A1')
     * @param {number} col - Column number (0-indexed), optional if row is cell reference
     * @param {*} value - Value to write
     * @param {Format} format - Optional format
     */
    write(row, col, value, format, sheet = 'Sheet1') {
        // Handle A1 notation
        if (typeof row === 'string') {
            const cellInfo = xlCell2Ind(row);
            sheet = typeof col === 'string' ? col : sheet;
            format = typeof col === 'object' ? col : (typeof value === 'object' && !(value instanceof Format) ? value : format);
            value = typeof col !== 'string' && typeof col !== 'object' ? col : value;
            row = cellInfo.row - 1;
            col = cellInfo.column - 1;
        }
        
        const { sheetIndex } = this._getOrCreateSheet(sheet);
        const sheetObj = this.sheets[sheetIndex];
        
        // Ensure data array is large enough
        while (sheetObj.data.length <= row) {
            sheetObj.data.push([]);
        }
        while (sheetObj.data[row].length <= col) {
            sheetObj.data[row].push(null);
        }
        
        // Process the value
        const cellData = this._processCell(value, format);
        sheetObj.data[row][col] = cellData;
        
        // Update sheet bounds
        sheetObj.startRow = Math.min(sheetObj.startRow || 1, row + 1);
        sheetObj.startCol = Math.min(sheetObj.startCol || 1, col + 1);
        
        return this;
    }
    
    /**
     * Write a string to a cell
     */
    writeString(row, col, string, format, sheet = 'Sheet1') {
        return this.write(row, col, String(string), format, sheet);
    }
    
    /**
     * Write a number to a cell
     */
    writeNumber(row, col, number, format, sheet = 'Sheet1') {
        return this.write(row, col, Number(number), format, sheet);
    }
    
    /**
     * Write a formula to a cell
     */
    writeFormula(row, col, formula, format, sheet = 'Sheet1') {
        const formulaStr = formula.startsWith('=') ? formula : '=' + formula;
        return this.write(row, col, formulaStr, format, sheet);
    }
    
    /**
     * Write a blank cell with format
     */
    writeBlank(row, col, format, sheet = 'Sheet1') {
        return this.write(row, col, '', format, sheet);
    }
    
    /**
     * Write a boolean value
     */
    writeBoolean(row, col, value, format, sheet = 'Sheet1') {
        return this.write(row, col, Boolean(value), format, sheet);
    }
    
    /**
     * Write a hyperlink
     */
    writeUrl(row, col, url, format, displayText, sheet = 'Sheet1') {
        // For now, write as HYPERLINK formula
        const text = displayText || url;
        const formula = `=HYPERLINK("${url}","${text}")`;
        return this.writeFormula(row, col, formula, format, sheet);
    }
    
    /**
     * Write a row of data
     */
    writeRow(row, col, data, format, sheet = 'Sheet1') {
        if (typeof row === 'string') {
            const cellInfo = xlCell2Ind(row);
            sheet = typeof format === 'string' ? format : sheet;
            format = typeof col === 'object' && !(col instanceof Format) && !Array.isArray(col) ? col : format;
            data = Array.isArray(col) ? col : data;
            row = cellInfo.row - 1;
            col = cellInfo.column - 1;
        }
        
        for (let i = 0; i < data.length; i++) {
            this.write(row, col + i, data[i], format, sheet);
        }
        return this;
    }
    
    /**
     * Write a column of data
     */
    writeColumn(row, col, data, format, sheet = 'Sheet1') {
        if (typeof row === 'string') {
            const cellInfo = xlCell2Ind(row);
            sheet = typeof format === 'string' ? format : sheet;
            format = typeof col === 'object' && !(col instanceof Format) && !Array.isArray(col) ? col : format;
            data = Array.isArray(col) ? col : data;
            row = cellInfo.row - 1;
            col = cellInfo.column - 1;
        }
        
        for (let i = 0; i < data.length; i++) {
            this.write(row + i, col, data[i], format, sheet);
        }
        return this;
    }
    
    /**
     * Set column width and format
     * @param {string|number} firstCol - First column (A or 0)
     * @param {string|number} lastCol - Last column (optional)
     * @param {number} width - Column width in characters
     * @param {Format} format - Optional format
     * @param {Object} options - { hidden: bool }
     */
    setColumn(firstCol, lastCol, width, format, options = {}, sheet = 'Sheet1') {
        // Handle single column
        if (typeof lastCol === 'number' && width === undefined) {
            width = lastCol;
            lastCol = firstCol;
        }
        
        // Convert column letters to numbers
        let startCol = typeof firstCol === 'string' ? xlCell2Ind(firstCol + '1').column : firstCol + 1;
        let endCol = typeof lastCol === 'string' ? xlCell2Ind(lastCol + '1').column : (lastCol !== undefined ? lastCol + 1 : startCol);
        
        const { sheetIndex } = this._getOrCreateSheet(sheet);
        
        if (!this.columnInfo[sheetIndex]) {
            this.columnInfo[sheetIndex] = {};
        }
        
        for (let col = startCol; col <= endCol; col++) {
            this.columnInfo[sheetIndex][col] = {
                width: width,
                format: format,
                hidden: options.hidden || false
            };
        }
        
        return this;
    }
    
    /**
     * Set row height and format
     * @param {number} row - Row number (0-indexed)
     * @param {number} height - Row height in points
     * @param {Format} format - Optional format
     * @param {Object} options - { hidden: bool }
     */
    setRow(row, height, format, options = {}, sheet = 'Sheet1') {
        const { sheetIndex } = this._getOrCreateSheet(sheet);
        
        if (!this.rowInfo[sheetIndex]) {
            this.rowInfo[sheetIndex] = {};
        }
        
        this.rowInfo[sheetIndex][row + 1] = {
            height: height,
            format: format,
            hidden: options.hidden || false
        };
        
        return this;
    }
    
    /**
     * Merge a range of cells
     */
    mergeRange(firstRow, firstCol, lastRow, lastCol, data, format, sheet = 'Sheet1') {
        // Handle A1:B2 notation
        if (typeof firstRow === 'string' && firstRow.includes(':')) {
            const parts = firstRow.split(':');
            const start = xlCell2Ind(parts[0]);
            const end = xlCell2Ind(parts[1]);
            sheet = typeof lastRow === 'string' ? lastRow : sheet;
            format = typeof lastCol === 'object' ? lastCol : format;
            data = firstCol;
            firstRow = start.row - 1;
            firstCol = start.column - 1;
            lastRow = end.row - 1;
            lastCol = end.column - 1;
        }
        
        const { sheetIndex } = this._getOrCreateSheet(sheet);
        
        if (!this.mergeCells[sheetIndex]) {
            this.mergeCells[sheetIndex] = [];
        }
        
        this.mergeCells[sheetIndex].push({
            startRow: firstRow + 1,
            startCol: firstCol + 1,
            endRow: lastRow + 1,
            endCol: lastCol + 1
        });
        
        // Write value to top-left cell
        if (data !== undefined) {
            this.write(firstRow, firstCol, data, format, sheet);
        }
        
        return this;
    }
    
    /**
     * Insert a chart into the worksheet
     */
    insertChart(row, col, chart, options = {}, sheet = 'Sheet1') {
        if (typeof row === 'string') {
            const cellInfo = xlCell2Ind(row);
            sheet = typeof options === 'string' ? options : sheet;
            options = typeof chart === 'object' && !chart.series ? chart : options;
            chart = col;
            row = cellInfo.row - 1;
            col = cellInfo.column - 1;
        }
        
        const { sheetIndex } = this._getOrCreateSheet(sheet);
        
        // Set chart position
        chart.x = (options.x_offset || 0) + col * 64;
        chart.y = (options.y_offset || 0) + row * 20;
        
        this.sheets[sheetIndex].chart = chart;
        
        return this;
    }
    
    /**
     * Process a single cell value
     * @private
     */
    _processCell(value, format) {
        let cellData = { value: value, type: 'n', format: format };
        
        if (value === null || value === undefined) {
            cellData = { value: '', type: 'n', format: format };
        } else if (typeof value === 'string') {
            if (value.startsWith('=')) {
                // Formula
                cellData = { value: value.substring(1), type: 'str', isFormula: true, format: format };
            } else if (value === '') {
                cellData = { value: '', type: 'n', format: format };
            } else {
                // Shared string - O(1) lookup with Map
                let idx = this.sharedStringsMap.get(value);
                if (idx === undefined) {
                    idx = this.sharedStrings.length;
                    this.sharedStrings.push(value);
                    this.sharedStringsMap.set(value, idx);
                }
                cellData = { value: idx, type: 's', format: format };
            }
        } else if (typeof value === 'boolean') {
            cellData = { value: value ? 1 : 0, type: 'b', format: format };
        } else if (typeof value === 'number') {
            if (value === Infinity) cellData.value = 9.99999999999999E+307;
            else if (value === -Infinity) cellData.value = -9.99999999999999E+307;
            else if (isNaN(value)) cellData.value = '';
        }
        
        return cellData;
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
        
        // Check if sheet already exists
        let existingSheetIndex = this.sheets.findIndex(s => s.name === sheetName);
        let sheetObj;
        
        if (existingSheetIndex >= 0) {
            sheetObj = this.sheets[existingSheetIndex];
        } else {
            sheetObj = {
                name: sheetName,
                data: [],
                startRow,
                startCol,
                chart: options.chart || null,
                comments: options.comments || []
            };
            this.sheets.push(sheetObj);
            existingSheetIndex = this.sheets.length - 1;
        }
        
        // Process data and collect shared strings
        for (let r = 0; r < fullData.length; r++) {
            const row = fullData[r];
            const rowIdx = startRow - 1 + r;
            
            // Ensure data array is large enough
            while (sheetObj.data.length <= rowIdx) {
                sheetObj.data.push([]);
            }
            
            for (let c = 0; c < row.length; c++) {
                const colIdx = startCol - 1 + c;
                const cell = row[c];
                
                // Ensure row is large enough
                while (sheetObj.data[rowIdx].length <= colIdx) {
                    sheetObj.data[rowIdx].push(null);
                }
                
                sheetObj.data[rowIdx][colIdx] = this._processCell(cell, null);
            }
        }
        
        // Update bounds
        sheetObj.startRow = Math.min(sheetObj.startRow || startRow, startRow);
        sheetObj.startCol = Math.min(sheetObj.startCol || startCol, startCol);
        
        // Store chart if provided
        if (options.chart) {
            sheetObj.chart = options.chart;
        }
        
        return this;
    }
    
    /**
     * Generate the sheet data XML
     */
    _generateSheetDataXML(sheet, sheetIndex) {
        let xml = '';
        const { data } = sheet;
        const rowInfoObj = this.rowInfo[sheetIndex] || {};
        
        for (let r = 0; r < data.length; r++) {
            const row = data[r];
            // Skip completely empty rows
            if (!row || row.length === 0) continue;
            
            // Check if row has any non-empty cells
            const hasContent = row.some(cell => 
                cell && (cell.value !== '' && cell.value !== null && cell.value !== undefined)
            );
            
            // Also check if row has custom height
            const rowInfo = rowInfoObj[r + 1];
            
            if (!hasContent && !rowInfo) continue;
            
            const rowNum = r + 1;
            const maxCol = row.length;
            
            let rowAttrs = `r="${rowNum}" spans="1:${maxCol}"`;
            if (rowInfo) {
                if (rowInfo.height) {
                    rowAttrs += ` ht="${rowInfo.height}" customHeight="1"`;
                }
                if (rowInfo.hidden) {
                    rowAttrs += ` hidden="1"`;
                }
                if (rowInfo.format && rowInfo.format.xfIndex) {
                    rowAttrs += ` s="${rowInfo.format.xfIndex}" customFormat="1"`;
                }
            }
            
            xml += `<row ${rowAttrs}>`;
            
            for (let c = 0; c < row.length; c++) {
                const cell = row[c];
                if (!cell) continue;
                
                const colNum = c + 1;
                const cellRef = xlColumn(colNum) + rowNum;
                
                // Get format index
                let styleAttr = '';
                if (cell.format && cell.format.xfIndex !== null && cell.format.xfIndex !== undefined) {
                    styleAttr = ` s="${cell.format.xfIndex}"`;
                }
                
                if (cell.isFormula) {
                    xml += `<c r="${cellRef}"${styleAttr}><f>${escapeXml(cell.value)}</f></c>`;
                } else if (cell.value === '' || cell.value === null || cell.value === undefined) {
                    // Skip empty cells unless they have formatting
                    if (styleAttr) {
                        xml += `<c r="${cellRef}"${styleAttr}/>`;
                    }
                } else if (cell.type === 'n') {
                    // Number - don't include t attribute for numbers
                    xml += `<c r="${cellRef}"${styleAttr}><v>${cell.value}</v></c>`;
                } else {
                    xml += `<c r="${cellRef}" t="${cell.type}"${styleAttr}><v>${cell.value}</v></c>`;
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
        
        // Generate chart type-specific XML
        const chartType = chart.type || 'scatter';
        xml += this._generateChartTypeXML(chart, chartType, sheetName, dataInfo);
        
        // X axis
        xml += this._generateAxisXML(chart.xAxis, 'b', chart.yAxis.id, chartType);
        
        // Y axis
        xml += this._generateAxisXML(chart.yAxis, 'l', chart.xAxis.id, chartType);
        
        // Secondary axes if needed
        if (chart.y2Axis && chart.y2Axis.visible) {
            xml += this._generateAxisXML(chart.x2Axis, 't', chart.y2Axis.id, chartType, true);
            xml += this._generateAxisXML(chart.y2Axis, 'r', chart.x2Axis.id, chartType, true);
        }
        
        xml += '</c:plotArea>';
        
        // Legend with configurable font size
        const legendPos = chart.legend?.position || 'r';
        if (legendPos !== 'none') {
            const legendFontSize = chart.legend?.fontSize || 10;
            xml += '<c:legend>';
            xml += `<c:legendPos val="${legendPos}"/>`;
            xml += '<c:layout/>';
            xml += '<c:overlay val="0"/>';
            xml += '<c:txPr>';
            xml += '<a:bodyPr/>';
            xml += '<a:lstStyle/>';
            xml += '<a:p>';
            xml += `<a:pPr><a:defRPr sz="${legendFontSize * 100}"/></a:pPr>`;
            xml += '<a:endParaRPr lang="en-US"/>';
            xml += '</a:p>';
            xml += '</c:txPr>';
            xml += '</c:legend>';
        }
        
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
     * Generate chart type-specific XML
     */
    _generateChartTypeXML(chart, chartType, sheetName, dataInfo) {
        let xml = '';
        
        switch (chartType) {
            case 'scatter':
                xml += this._generateScatterChartXML(chart, sheetName, dataInfo);
                break;
            case 'line':
                xml += this._generateLineChartXML(chart, sheetName, dataInfo);
                break;
            case 'column':
            case 'bar':
                xml += this._generateBarChartXML(chart, sheetName, dataInfo, chartType);
                break;
            case 'area':
                xml += this._generateAreaChartXML(chart, sheetName, dataInfo);
                break;
            case 'pie':
                xml += this._generatePieChartXML(chart, sheetName, dataInfo);
                break;
            case 'doughnut':
                xml += this._generateDoughnutChartXML(chart, sheetName, dataInfo);
                break;
            default:
                xml += this._generateScatterChartXML(chart, sheetName, dataInfo);
        }
        
        return xml;
    }
    
    /**
     * Generate scatter chart XML
     */
    _generateScatterChartXML(chart, sheetName, dataInfo) {
        let xml = '';
        const scatterStyle = chart.scatterStyle || 'lineMarker';
        
        xml += '<c:scatterChart>';
        xml += `<c:scatterStyle val="${scatterStyle}"/>`;
        xml += '<c:varyColors val="0"/>';
        
        // Generate series
        for (let i = 0; i < chart.series.length; i++) {
            xml += this._generateScatterSeriesXML(chart.series[i], i, sheetName, dataInfo, chart);
        }
        
        xml += `<c:axId val="${chart.xAxis.id}"/>`;
        xml += `<c:axId val="${chart.yAxis.id}"/>`;
        xml += '</c:scatterChart>';
        
        return xml;
    }
    
    /**
     * Generate line chart XML
     */
    _generateLineChartXML(chart, sheetName, dataInfo) {
        let xml = '';
        const grouping = chart.grouping || 'standard';
        
        xml += '<c:lineChart>';
        xml += `<c:grouping val="${grouping}"/>`;
        xml += '<c:varyColors val="0"/>';
        
        for (let i = 0; i < chart.series.length; i++) {
            xml += this._generateLineSeriesXML(chart.series[i], i, sheetName, dataInfo, chart);
        }
        
        xml += '<c:marker val="1"/>';
        xml += `<c:axId val="${chart.xAxis.id}"/>`;
        xml += `<c:axId val="${chart.yAxis.id}"/>`;
        xml += '</c:lineChart>';
        
        return xml;
    }
    
    /**
     * Generate bar/column chart XML
     */
    _generateBarChartXML(chart, sheetName, dataInfo, chartType) {
        let xml = '';
        const barDir = chartType === 'bar' ? 'bar' : 'col';
        const grouping = chart.grouping || 'clustered';
        
        xml += '<c:barChart>';
        xml += `<c:barDir val="${barDir}"/>`;
        xml += `<c:grouping val="${grouping}"/>`;
        xml += '<c:varyColors val="0"/>';
        
        for (let i = 0; i < chart.series.length; i++) {
            xml += this._generateBarSeriesXML(chart.series[i], i, sheetName, dataInfo);
        }
        
        xml += `<c:gapWidth val="${chart.gapWidth || 150}"/>`;
        if (grouping === 'clustered' || grouping === 'stacked' || grouping === 'percentStacked') {
            xml += `<c:overlap val="${chart.overlap || 0}"/>`;
        }
        xml += `<c:axId val="${chart.xAxis.id}"/>`;
        xml += `<c:axId val="${chart.yAxis.id}"/>`;
        xml += '</c:barChart>';
        
        return xml;
    }
    
    /**
     * Generate area chart XML
     */
    _generateAreaChartXML(chart, sheetName, dataInfo) {
        let xml = '';
        const grouping = chart.grouping || 'standard';
        
        xml += '<c:areaChart>';
        xml += `<c:grouping val="${grouping}"/>`;
        xml += '<c:varyColors val="0"/>';
        
        for (let i = 0; i < chart.series.length; i++) {
            xml += this._generateAreaSeriesXML(chart.series[i], i, sheetName, dataInfo);
        }
        
        xml += `<c:axId val="${chart.xAxis.id}"/>`;
        xml += `<c:axId val="${chart.yAxis.id}"/>`;
        xml += '</c:areaChart>';
        
        return xml;
    }
    
    /**
     * Generate pie chart XML
     */
    _generatePieChartXML(chart, sheetName, dataInfo) {
        let xml = '';
        
        xml += '<c:pieChart>';
        xml += '<c:varyColors val="1"/>';
        
        for (let i = 0; i < chart.series.length; i++) {
            xml += this._generatePieSeriesXML(chart.series[i], i, sheetName, dataInfo);
        }
        
        xml += '<c:firstSliceAng val="0"/>';
        xml += '</c:pieChart>';
        
        return xml;
    }
    
    /**
     * Generate doughnut chart XML
     */
    _generateDoughnutChartXML(chart, sheetName, dataInfo) {
        let xml = '';
        
        xml += '<c:doughnutChart>';
        xml += '<c:varyColors val="1"/>';
        
        for (let i = 0; i < chart.series.length; i++) {
            xml += this._generatePieSeriesXML(chart.series[i], i, sheetName, dataInfo);
        }
        
        xml += '<c:firstSliceAng val="0"/>';
        xml += `<c:holeSize val="${chart.holeSize || 50}"/>`;
        xml += '</c:doughnutChart>';
        
        return xml;
    }
    
    /**
 * Generate series name XML element
 * @private
 */
    _generateSeriesNameXML(series, index, sheetName, dataInfo) {
        if (!series.name?.text) return '';
        
        if (dataInfo?.numRows > 1) {
            const headerCol = xlColumn(dataInfo.startCol + index + 1);
            const headerRow = dataInfo.startRow;
            const safeSheetName = escapeSheetName(sheetName);
            return `<c:tx><c:strRef><c:f>${safeSheetName}!$${headerCol}$${headerRow}</c:f></c:strRef></c:tx>`;
        }
        return `<c:tx><c:v>${escapeXml(series.name.text)}</c:v></c:tx>`;
    }

    /**
     * Generate common series header (idx, order, name)
     * @private
     */
    _generateSeriesHeader(series, index, sheetName, dataInfo) {
        return `<c:ser>` +
            `<c:idx val="${index}"/>` +
            `<c:order val="${index}"/>` +
            this._generateSeriesNameXML(series, index, sheetName, dataInfo);
    }

    /**
     * Generate scatter series XML
     */
    _generateScatterSeriesXML(series, index, sheetName, dataInfo, chart) {
        const parts = [
            this._generateSeriesHeader(series, index, sheetName, dataInfo),
            this._generateSeriesSpPr(series, chart),
            this._generateMarkerXML(series.marker, series, chart),
            series.dataLabels ? this._generateDataLabelsXML(series.dataLabels) : '',
            series.trendline ? this._generateTrendlineXML(series.trendline) : '',
            this._generateXValXML(series, index, sheetName, dataInfo),
            this._generateYValXML(series, index, sheetName, dataInfo),
            `<c:smooth val="${series.smooth ? '1' : '0'}"/>`,
            '</c:ser>'
        ];
        return parts.join('');
    }
    
    /**
     * Generate line series XML
     */
    _generateLineSeriesXML(series, index, sheetName, dataInfo, chart) {
        const parts = [
            this._generateSeriesHeader(series, index, sheetName, dataInfo),
            this._generateSeriesSpPr(series, chart),
            this._generateMarkerXML(series.marker, series, chart),
            this._generateCatXML(series, index, sheetName, dataInfo),
            this._generateValXML(series, index, sheetName, dataInfo),
            `<c:smooth val="${series.smooth ? '1' : '0'}"/>`,
            '</c:ser>'
        ];
        return parts.join('');
    }
    
    /**
     * Generate bar series XML
     */
    _generateBarSeriesXML(series, index, sheetName, dataInfo) {
        const parts = [
            this._generateSeriesHeader(series, index, sheetName, dataInfo),
            this._generateBarSpPr(series),
            this._generateCatXML(series, index, sheetName, dataInfo),
            this._generateValXML(series, index, sheetName, dataInfo),
            '</c:ser>'
        ];
        return parts.join('');
    }
    
    /**
     * Generate area series XML
     */
    _generateAreaSeriesXML(series, index, sheetName, dataInfo) {
        const parts = [
            this._generateSeriesHeader(series, index, sheetName, dataInfo),
            this._generateBarSpPr(series),
            this._generateCatXML(series, index, sheetName, dataInfo),
            this._generateValXML(series, index, sheetName, dataInfo),
            '</c:ser>'
        ];
        return parts.join('');
    }
    
    /**
     * Generate pie series XML
     */
    _generatePieSeriesXML(series, index, sheetName, dataInfo) {
        const parts = [
            this._generateSeriesHeader(series, index, sheetName, dataInfo),
            this._generateCatXML(series, index, sheetName, dataInfo),
            this._generateValXML(series, index, sheetName, dataInfo),
            '</c:ser>'
        ];
        return parts.join('');
    }
    
    /**
     * Generate solid fill XML element
     * @private
     */
    _generateSolidFillXML(color) {
        if (!color) return '';
        const hexColor = toHexColor(color);
        return `<a:solidFill><a:srgbClr val="${hexColor}"/></a:solidFill>`;
    }

    /**
     * Generate line XML element
     * @private
     */
    _generateLineXML(line) {
        if (!line?.color) return '';
        
        const { color, width = 2, dashType = 'solid' } = line;
        
        if (color.option === 'None') {
            return '<a:ln><a:noFill/></a:ln>';
        }
        
        if (color.option === 'Solid' && color.value) {
            const hexColor = toHexColor(color.value);
            const lineWidth = width * PT_TO_EMU;
            return `<a:ln w="${lineWidth}">` +
                `<a:solidFill><a:srgbClr val="${hexColor}"/></a:solidFill>` +
                `<a:prstDash val="${dashType}"/>` +
                '</a:ln>';
        }
        
        return '';
    }

    /**
     * Generate series shape properties (line style)
     */
    _generateSeriesSpPr(series, chart) {
        return '<c:spPr>' + this._generateLineXML(series.line) + '</c:spPr>';
    }
    
    /**
     * Generate bar/area shape properties (fill)
     */
    _generateBarSpPr(series) {
        const fill = series.line?.color?.value 
            ? this._generateSolidFillXML(series.line.color.value) 
            : '';
        return '<c:spPr>' + fill + '</c:spPr>';
    }
    
    /**
     * Generate marker XML
     */
    _generateMarkerXML(marker, series, chart) {
        // No marker or explicitly disabled
        if (!marker || marker.option === 'NoMarker' || marker.option === 'none') {
            return '<c:marker><c:symbol val="none"/></c:marker>';
        }
        
        // Auto marker - let Excel choose
        if (marker.option === 'Automatic' || marker.option === 'auto') {
            return '';
        }
        
        // Built-in marker
        const markerType = MARKER_TYPES[marker.type] || marker.type || 'circle';
        const markerSize = marker.size || 5;
        
        const parts = [
            '<c:marker>',
            `<c:symbol val="${markerType}"/>`,
            `<c:size val="${markerSize}"/>`
        ];
        
        // Marker fill and line styling
        if (marker.fillColor || marker.line) {
            parts.push('<c:spPr>');
            
            if (marker.fillColor?.option === 'Solid' && marker.fillColor.value) {
                parts.push(this._generateSolidFillXML(marker.fillColor.value));
            }
            
            if (marker.line?.color?.option === 'Solid' && marker.line.color.value) {
                const hexColor = toHexColor(marker.line.color.value);
                const lineWidth = (marker.line.width || 0.75) * PT_TO_EMU;
                parts.push(`<a:ln w="${lineWidth}"><a:solidFill><a:srgbClr val="${hexColor}"/></a:solidFill></a:ln>`);
            }
            
            parts.push('</c:spPr>');
        }
        
        parts.push('</c:marker>');
        return parts.join('');
    }
    
    /**
     * Generate numeric literal data points XML
     * @private
     */
    _generateNumericPointsXML(values) {
        const points = values
            .map((val, idx) => (val !== null && val !== undefined && !isNaN(val))
                ? `<c:pt idx="${idx}"><c:v>${val}</c:v></c:pt>`
                : '')
            .filter(Boolean)
            .join('');
        
        return '<c:formatCode>General</c:formatCode>' +
            `<c:ptCount val="${values.length}"/>` +
            points;
    }

    /**
     * Generate cell reference range string
     * @private
     */
    _generateCellRange(sheetName, col, startRow, endRow) {
        const colLetter = xlColumn(col);
        const safeSheetName = escapeSheetName(sheetName);
        return `${safeSheetName}!$${colLetter}$${startRow}:$${colLetter}$${endRow}`;
    }

    /**
     * Generate X values XML for scatter chart
     */
    _generateXValXML(series, index, sheetName, dataInfo) {
        if (dataInfo?.numRows > 1) {
            const startRow = dataInfo.startRow + 1;
            const endRow = dataInfo.startRow + dataInfo.numRows - 1;
            const range = this._generateCellRange(sheetName, dataInfo.startCol, startRow, endRow);
            return `<c:xVal><c:numRef><c:f>${range}</c:f></c:numRef></c:xVal>`;
        }
        
        if (series.x?.values?.length > 0) {
            return '<c:xVal><c:numLit>' +
                this._generateNumericPointsXML(series.x.values) +
                '</c:numLit></c:xVal>';
        }
        
        return '';
    }
    
    /**
     * Generate Y values XML for scatter chart
     */
    _generateYValXML(series, index, sheetName, dataInfo) {
        if (dataInfo?.numRows > 1) {
            const startRow = dataInfo.startRow + 1;
            const endRow = dataInfo.startRow + dataInfo.numRows - 1;
            const range = this._generateCellRange(sheetName, dataInfo.startCol + index + 1, startRow, endRow);
            return `<c:yVal><c:numRef><c:f>${range}</c:f></c:numRef></c:yVal>`;
        }
        
        if (series.y?.values?.length > 0) {
            return '<c:yVal><c:numLit>' +
                this._generateNumericPointsXML(series.y.values) +
                '</c:numLit></c:yVal>';
        }
        
        return '';
    }
    
    /**
     * Generate category XML for line/bar/area/pie charts
     */
    _generateCatXML(series, index, sheetName, dataInfo) {
        const values = series.x?.values;
        if (!values?.length) return '';
        
        const isString = typeof values[0] === 'string';
        const points = values
            .map((val, idx) => `<c:pt idx="${idx}"><c:v>${isString ? escapeXml(val) : val}</c:v></c:pt>`)
            .join('');
        
        if (isString) {
            return '<c:cat><c:strLit>' +
                `<c:ptCount val="${values.length}"/>` +
                points +
                '</c:strLit></c:cat>';
        }
        
        return '<c:cat><c:numLit>' +
            '<c:formatCode>General</c:formatCode>' +
            `<c:ptCount val="${values.length}"/>` +
            points +
            '</c:numLit></c:cat>';
    }
    
    /**
     * Generate values XML for line/bar/area/pie charts
     */
    _generateValXML(series, index, sheetName, dataInfo) {
        if (!series.y?.values?.length) return '';
        
        return '<c:val><c:numLit>' +
            this._generateNumericPointsXML(series.y.values) +
            '</c:numLit></c:val>';
    }
    
    /**
     * Generate data labels XML
     */
    _generateDataLabelsXML(dataLabels) {
        let xml = '<c:dLbls>';
        
        if (dataLabels.showValue) {
            xml += '<c:showVal val="1"/>';
        }
        if (dataLabels.showCatName) {
            xml += '<c:showCatName val="1"/>';
        }
        if (dataLabels.showSerName) {
            xml += '<c:showSerName val="1"/>';
        }
        if (dataLabels.showPercent) {
            xml += '<c:showPercent val="1"/>';
        }
        
        xml += '<c:showLegendKey val="0"/>';
        xml += '</c:dLbls>';
        return xml;
    }
    
    /**
     * Generate trendline XML
     */
    _generateTrendlineXML(trendline) {
        let xml = '<c:trendline>';
        
        // Trendline type
        const type = trendline.type || 'linear';
        xml += `<c:trendlineType val="${type}"/>`;
        
        // Polynomial order
        if (type === 'poly' && trendline.order) {
            xml += `<c:order val="${trendline.order}"/>`;
        }
        
        // Period for moving average
        if (type === 'movingAvg' && trendline.period) {
            xml += `<c:period val="${trendline.period}"/>`;
        }
        
        // Forward/backward projection
        if (trendline.forward) {
            xml += `<c:forward val="${trendline.forward}"/>`;
        }
        if (trendline.backward) {
            xml += `<c:backward val="${trendline.backward}"/>`;
        }
        
        // Display equation/R-squared
        if (trendline.displayEquation) {
            xml += '<c:dispEq val="1"/>';
        }
        if (trendline.displayRSquared) {
            xml += '<c:dispRSqr val="1"/>';
        }
        
        xml += '</c:trendline>';
        return xml;
    }
    
    /**
     * Generate axis XML
     */
    _generateAxisXML(axis, position, crossAxisId, chartType = 'scatter', isSecondary = false) {
        const isLogScale = axis.logBase && !isNaN(axis.logBase) && axis.logBase > 1;
        
        // For non-scatter charts, X axis is a category axis
        const isXAxis = position === 'b' || position === 't';
        const useCategoryAxis = isXAxis && chartType !== 'scatter';
        
        let xml = useCategoryAxis ? '<c:catAx>' : '<c:valAx>';
        xml += `<c:axId val="${axis.id}"/>`;
        
        // Scaling with optional log scale and min/max
        xml += '<c:scaling>';
        if (isLogScale && !useCategoryAxis) {
            xml += `<c:logBase val="${axis.logBase}"/>`;
        }
        xml += '<c:orientation val="minMax"/>';
        if (!useCategoryAxis) {
            if (axis.maximum !== undefined && !isNaN(axis.maximum)) {
                xml += `<c:max val="${axis.maximum}"/>`;
            }
            if (axis.minimum !== undefined && !isNaN(axis.minimum)) {
                xml += `<c:min val="${axis.minimum}"/>`;
            }
        }
        xml += '</c:scaling>';
        
        xml += '<c:delete val="0"/>';
        xml += `<c:axPos val="${position}"/>`;
        
        // Major gridlines (typically only for value axes)
        if (!useCategoryAxis && axis.majorGridlines !== false) {
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
        if (!useCategoryAxis && axis.minorGridlines) {
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
        
        // Tick label font properties
        const tickLblFontSize = axis.tickLabelFontSize || axis.fontSize || 10;
        xml += '<c:txPr>';
        xml += '<a:bodyPr/>';
        xml += '<a:lstStyle/>';
        xml += '<a:p>';
        xml += `<a:pPr><a:defRPr sz="${tickLblFontSize * 100}"/></a:pPr>`;
        xml += '<a:endParaRPr lang="en-US"/>';
        xml += '</a:p>';
        xml += '</c:txPr>';
        
        xml += `<c:crossAx val="${crossAxisId}"/>`;
        xml += '<c:crosses val="autoZero"/>';
        
        if (useCategoryAxis) {
            xml += '<c:auto val="1"/>';
            xml += '<c:lblAlgn val="ctr"/>';
            xml += '<c:lblOffset val="100"/>';
            xml += '</c:catAx>';
        } else {
            xml += '<c:crossBetween val="midCat"/>';
            xml += '</c:valAx>';
        }
        
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
            const path = require('path');
            
            // SECURITY: Validate filename to prevent path traversal
            const resolvedPath = path.resolve(filename);
            const baseDir = process.cwd();
            if (!resolvedPath.startsWith(baseDir + path.sep) && resolvedPath !== baseDir) {
                throw new Error('Security error: output path must be within working directory');
            }
            
            // SECURITY: Ensure .xlsx extension to prevent arbitrary file writes
            if (!resolvedPath.toLowerCase().endsWith('.xlsx')) {
                throw new Error('Security error: output file must have .xlsx extension');
            }
            
            fs.writeFileSync(resolvedPath, content);
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
    /**
     * Build style collections (fonts, fills, borders) from formats
     * @private
     */
    _buildStyleCollections() {
        const fonts = ['<font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/><scheme val="minor"/></font>'];
        const fills = [
            '<fill><patternFill patternType="none"/></fill>',
            '<fill><patternFill patternType="gray125"/></fill>'
        ];
        const borders = ['<border><left/><right/><top/><bottom/><diagonal/></border>'];
        
        const fontMap = { 'default': 0 };
        const fillMap = { 'none': 0, 'gray125': 1 };
        const borderMap = { 'default': 0 };
        
        for (const format of this.formats) {
            this._addUniqueStyle(fonts, fontMap, this._buildFontKey(format), () => this._buildFontXML(format));
            this._addUniqueStyle(fills, fillMap, this._buildFillKey(format), () => this._buildFillXML(format));
            this._addUniqueStyle(borders, borderMap, this._buildBorderKey(format), () => this._buildBorderXML(format));
        }
        
        return { fonts, fills, borders, fontMap, fillMap, borderMap };
    }

    /**
     * Add unique style to collection if not already present
     * @private
     */
    _addUniqueStyle(collection, map, key, buildFn) {
        if (!Object.prototype.hasOwnProperty.call(map, key)) {
            map[key] = collection.length;
            collection.push(buildFn());
        }
    }

    /**
     * Generate custom number formats XML
     * @private
     */
    _buildNumFormatsXML() {
        if (this.customNumFormats.size === 0) return '';
        
        const formats = Array.from(this.customNumFormats.entries())
            .map(([fmt, id]) => `<numFmt numFmtId="${id}" formatCode="${escapeXmlAttr(fmt)}"/>`)
            .join('');
        
        return `<numFmts count="${this.customNumFormats.size}">${formats}</numFmts>`;
    }

    _addStyles() {
        const { fonts, fills, borders, fontMap, fillMap, borderMap } = this._buildStyleCollections();
        
        const parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
            this._buildNumFormatsXML(),
            `<fonts count="${fonts.length}">${fonts.join('')}</fonts>`,
            `<fills count="${fills.length}">${fills.join('')}</fills>`,
            `<borders count="${borders.length}">${borders.join('')}</borders>`,
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        ];
        
        // Cell XFs
        const cellXfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']; // Default format
        
        for (const format of this.formats) {
            const fontId = fontMap[this._buildFontKey(format)];
            const fillId = fillMap[this._buildFillKey(format)];
            const borderId = borderMap[this._buildBorderKey(format)];
            const numFmtId = format.numFmtId || 0;
            
            let xfXml = `<xf numFmtId="${numFmtId}" fontId="${fontId}" fillId="${fillId}" borderId="${borderId}" xfId="0"`;
            
            // Apply flags
            if (numFmtId !== 0) xfXml += ' applyNumberFormat="1"';
            if (fontId !== 0) xfXml += ' applyFont="1"';
            if (fillId !== 0) xfXml += ' applyFill="1"';
            if (borderId !== 0) xfXml += ' applyBorder="1"';
            
            // Alignment
            const hasAlignment = format.align || format.valign || format.textWrap || format.rotation || format.indent;
            if (hasAlignment) {
                xfXml += ' applyAlignment="1">';
                xfXml += '<alignment';
                if (format.align) xfXml += ` horizontal="${format.align}"`;
                if (format.valign) xfXml += ` vertical="${format.valign}"`;
                if (format.textWrap) xfXml += ' wrapText="1"';
                if (format.rotation) xfXml += ` textRotation="${format.rotation}"`;
                if (format.indent) xfXml += ` indent="${format.indent}"`;
                xfXml += '/></xf>';
            } else {
                xfXml += '/>';
            }
            
            cellXfs.push(xfXml);
        }
        
        parts.push(
            `<cellXfs count="${cellXfs.length}">${cellXfs.join('')}</cellXfs>`,
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>',
            '<dxfs count="0"/>',
            '<tableStyles count="0" defaultTableStyle="TableStyleMedium9" defaultPivotStyle="PivotStyleLight16"/>',
            '</styleSheet>'
        );
        
        this.zip.file('xl/styles.xml', parts.join('\n'));
    }
    
    /**
     * Build font key for deduplication
     */
    _buildFontKey(format) {
        return JSON.stringify({
            name: format.fontName,
            size: format.fontSize,
            bold: format.bold,
            italic: format.italic,
            underline: format.underline,
            strikeout: format.strikeout,
            fontColor: format.fontColor
        });
    }
    
    /**
     * Build font XML
     */
    _buildFontXML(format) {
        const parts = ['<font>'];
        
        // Font style flags
        if (format.bold) parts.push('<b/>');
        if (format.italic) parts.push('<i/>');
        if (format.underline) parts.push('<u/>');
        if (format.strikeout) parts.push('<strike/>');
        
        // Font size and color
        parts.push(`<sz val="${format.fontSize || DEFAULT_FONT.SIZE}"/>`);
        parts.push(format.fontColor 
            ? `<color rgb="FF${format.fontColor.toUpperCase()}"/>` 
            : '<color theme="1"/>');
        
        // Font name and family
        const fontName = format.fontName || DEFAULT_FONT.NAME;
        parts.push(`<name val="${fontName}"/>`);
        parts.push(`<family val="${DEFAULT_FONT.FAMILY}"/>`);
        
        if (fontName === DEFAULT_FONT.NAME) {
            parts.push('<scheme val="minor"/>');
        }
        
        parts.push('</font>');
        return parts.join('');
    }
    
    /**
     * Build fill key for deduplication
     */
    _buildFillKey(format) {
        return JSON.stringify({
            bgColor: format.bgColor,
            pattern: format.pattern
        });
    }
    
    /**
     * Build fill XML
     */
    _buildFillXML(format) {
        if (!format.bgColor) {
            return '<fill><patternFill patternType="none"/></fill>';
        }
        const pattern = format.pattern || 'solid';
        let xml = `<fill><patternFill patternType="${pattern}">`;
        xml += `<fgColor rgb="FF${format.bgColor.toUpperCase()}"/>`;
        xml += '</patternFill></fill>';
        return xml;
    }
    
    /**
     * Build border key for deduplication
     */
    _buildBorderKey(format) {
        return JSON.stringify({
            left: format.left,
            right: format.right,
            top: format.top,
            bottom: format.bottom,
            leftColor: format.leftColor,
            rightColor: format.rightColor,
            topColor: format.topColor,
            bottomColor: format.bottomColor
        });
    }
    
    /**
     * Build border XML
     */
    _buildBorderXML(format) {
        let xml = '<border>';
        xml += this._buildBorderSideXML('left', format.left, format.leftColor);
        xml += this._buildBorderSideXML('right', format.right, format.rightColor);
        xml += this._buildBorderSideXML('top', format.top, format.topColor);
        xml += this._buildBorderSideXML('bottom', format.bottom, format.bottomColor);
        xml += '<diagonal/>';
        xml += '</border>';
        return xml;
    }
    
    /**
     * Build individual border side XML
     */
    _buildBorderSideXML(side, style, color) {
        if (!style || style === 0) return `<${side}/>`;
        const styleMap = {
            1: 'thin', 2: 'medium', 3: 'dashed', 4: 'dotted', 5: 'thick',
            6: 'double', 7: 'hair', 8: 'mediumDashed', 9: 'dashDot',
            10: 'mediumDashDot', 11: 'dashDotDot', 12: 'mediumDashDotDot', 13: 'slantDashDot'
        };
        const styleName = typeof style === 'number' ? (styleMap[style] || 'thin') : style;
        let xml = `<${side} style="${styleName}">`;
        if (color) {
            xml += `<color rgb="FF${color.toUpperCase()}"/>`;
        } else {
            xml += '<color auto="1"/>';
        }
        xml += `</${side}>`;
        return xml;
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
            
            // Column widths
            const colInfo = this.columnInfo[i];
            if (colInfo && Object.keys(colInfo).length > 0) {
                xml += '<cols>';
                // Sort by column number
                const sortedCols = Object.entries(colInfo).sort((a, b) => Number(a[0]) - Number(b[0]));
                for (const [col, info] of sortedCols) {
                    xml += `<col min="${col}" max="${col}"`;
                    if (info.width !== undefined) xml += ` width="${info.width}"`;
                    if (info.hidden) xml += ' hidden="1"';
                    if (info.formatId) xml += ` style="${info.formatId}"`;
                    xml += ' customWidth="1"/>';
                }
                xml += '</cols>';
            }
            
            xml += '<sheetData>';
            xml += this._generateSheetDataXML(sheet, i);
            xml += '</sheetData>';
            
            // Merge cells
            const mergeCells = this.mergeCells[i];
            if (mergeCells && mergeCells.length > 0) {
                xml += `<mergeCells count="${mergeCells.length}">`;
                for (const merge of mergeCells) {
                    const startRef = xlColumn(merge.startCol) + merge.startRow;
                    const endRef = xlColumn(merge.endCol) + merge.endRow;
                    xml += `<mergeCell ref="${startRef}:${endRef}"/>`;
                }
                xml += '</mergeCells>';
            }
            
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
    
    /**
     * Insert an image into the worksheet
     * @param {string} sheetName - Sheet name
     * @param {number} row - Row number (1-based)
     * @param {number} col - Column number (1-based)
     * @param {string|ArrayBuffer|Uint8Array} image - Image path, data URL, or binary data
     * @param {Object} [options] - Options { xOffset, yOffset, xScale, yScale }
     */
    async insertImage(sheetName, row, col, image, options = {}) {
        const sheet = this._getOrCreateSheet(sheetName);
        if (!sheet.images) sheet.images = [];
        
        let imageData;
        let imageType = 'png';
        
        if (typeof image === 'string') {
            if (image.startsWith('data:')) {
                // Data URL - validate format strictly
                const match = image.match(/^data:image\/(png|jpe?g|gif|bmp|webp);base64,([A-Za-z0-9+/=]+)$/);
                if (match) {
                    imageType = match[1] === 'jpeg' ? 'jpeg' : match[1];
                    imageData = atob(match[2]);
                }
            } else {
                // File path - need to read (Node.js only)
                if (typeof require !== 'undefined') {
                    const fs = require('fs');
                    const path = require('path');
                    
                    // SECURITY: Validate path to prevent traversal attacks
                    const resolvedPath = path.resolve(image);
                    const baseDir = process.cwd();
                    if (!resolvedPath.startsWith(baseDir + path.sep) && resolvedPath !== baseDir) {
                        throw new Error('Security error: image path must be within working directory');
                    }
                    
                    // SECURITY: Validate file extension
                    const ext = path.extname(image).toLowerCase();
                    const allowedExts = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'];
                    if (!allowedExts.includes(ext)) {
                        throw new Error('Security error: invalid image type ' + ext);
                    }
                    
                    imageData = fs.readFileSync(resolvedPath);
                    imageType = ext.substring(1);
                    if (imageType === 'jpg') imageType = 'jpeg';
                }
            }
        } else if (image instanceof ArrayBuffer || image instanceof Uint8Array) {
            imageData = image;
        }
        
        if (imageData) {
            sheet.images.push({
                row,
                col,
                data: imageData,
                type: imageType,
                xOffset: options.xOffset || 0,
                yOffset: options.yOffset || 0,
                xScale: options.xScale || 1,
                yScale: options.yScale || 1
            });
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
        Format,
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
        DASH_TYPES,
        MARKER_TYPES,
        NUM_FORMATS,
        BORDER_STYLES,
        PATTERN_TYPES
    };
} else if (typeof window !== 'undefined') {
    // Browser
    window.XlsxWriter = XlsxWriter;
    window.Format = Format;
    window.xlsxwrite = {
        XlsxWriter,
        Format,
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
        DASH_TYPES,
        MARKER_TYPES,
        NUM_FORMATS,
        BORDER_STYLES,
        PATTERN_TYPES
    };
}
