/*
  PDF -> paragraphs, for the SKB reference checker.

  A .docx states its structure: <w:p> is a paragraph, w:pStyle names the style,
  <w:i> marks italic. A PDF states none of that. Its text layer is a bag of
  positioned glyph runs, and every structural fact the checker needs has to be
  reconstructed from geometry:

      paragraph boundaries   from line spacing, indentation and short lines
      headings               from font size relative to the body text
      italic / bold          from the embedded font's name
      superscript/subscript  from baseline offset and reduced size
      reading order          from column detection

  Some facts cannot be reconstructed at all, and the caller is told which so it
  can disable the rules that depend on them - see PDF_CAPABILITIES. The most
  consequential is the non-breaking space: a PDF records a position, not a
  character, so U+00A0 and U+0020 are indistinguishable once rendered. Running
  the hard-space rules over a PDF would report every number-plus-unit in the
  report as an error.

  The module is deliberately free of any pdf.js dependency: it takes plain
  numbers in and gives paragraphs out, so the geometry can be tested directly
  against synthetic input. See resources/tests/pdf/.
*/
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SkbPdf = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /*
    What a PDF cannot tell us. The checker turns each of these off rather than
    guessing, because a rule that cannot see its evidence does not fail
    quietly - it reports every correct occurrence as an error.
  */
  const PDF_CAPABILITIES = Object.freeze({
    'space-characters': false,  /* U+00A0 vs U+0020 is not recorded */
    'underline': false,         /* drawn as a graphic, not a text attribute */
    'field-codes': false,       /* Zotero field codes do not survive printing */
    'table-context': false,     /* cell membership is not in the text layer */
    'paragraph-styles': 'inferred',
    /*
      Italic and bold ARE recoverable, from the embedded fonts — but only if
      pdf.js managed to translate them, which it cannot always do. The reader
      sets this to false when it recovered no fonts at all, because the rule
      that wants quantity symbols italic would otherwise report every correct
      one as an error.
    */
    'character-styles': true
  });

  const DOCX_CAPABILITIES = Object.freeze({
    'space-characters': true, 'underline': true, 'field-codes': true,
    'table-context': true, 'paragraph-styles': true, 'character-styles': true
  });

  /* --------------------------- text repair --------------------------- */

  /*
    Ligatures are single glyphs in the font and arrive as single characters.
    Left alone, "identi<fi>ed" does not match /\bidentified\b/ and every rule
    that names a word silently stops working on the words that happen to
    contain fi.
  */
  const LIGATURES = {
    'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi',
    'ﬄ': 'ffl', 'ﬅ': 'st', 'ﬆ': 'st'
  };

  function normalisePdfText(value) {
    return String(value == null ? '' : value)
      .replace(/[ﬀ-ﬆ]/g, glyph => LIGATURES[glyph] || glyph)
      .replace(/­/g, '')                          /* soft hyphen: never real text */
      .replace(/[​‌‍﻿]/g, '')
      /*
        A PDF has no non-breaking space, so any U+00A0 in the text layer is an
        artefact of the extractor rather than the author's intent. Folding it to
        an ordinary space keeps it from reading as evidence that a hard space
        was used - the rules that need that evidence are disabled instead.
      */
      .replace(/[  -    　]/g, ' ');
  }

  /* ----------------------------- helpers ----------------------------- */

  function median(values) {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const middle = sorted.length >> 1;
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function quantile(values, fraction) {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(fraction * (sorted.length - 1))))];
  }

  /** The most common value, weighted, rounded to `step` so near-equal sizes agree. */
  function weightedMode(entries, step) {
    const buckets = new Map();
    for (const [value, weight] of entries) {
      const key = Math.round(value / step) * step;
      buckets.set(key, (buckets.get(key) || 0) + weight);
    }
    let best = 0;
    let bestWeight = -1;
    for (const [key, weight] of buckets) {
      if (weight > bestWeight) { best = key; bestWeight = weight; }
    }
    return best;
  }

  /* ------------------------- items into lines ------------------------ */

  /*
    Items on one typeset line share a baseline, but not exactly: a superscript
    sits about a third of an em higher, and a smaller inline font shifts the
    reported y as well. Grouping with a tolerance of half the line's font size
    keeps those with their line without swallowing the next one, whose leading
    is at least 1.1 em in any readable document.
  */
  function groupIntoLines(items) {
    const usable = (items || [])
      .filter(item => item && typeof item.str === 'string' && item.str.trim() !== '')
      .sort((a, b) => (b.y - a.y) || (a.x - b.x));

    const lines = [];
    let current = null;
    for (const item of usable) {
      const tolerance = Math.max(1.5, 0.5 * (item.fontSize || 10));
      if (!current || Math.abs(current.anchorY - item.y) > tolerance) {
        current = { items: [], anchorY: item.y, anchorSize: 0 };
        lines.push(current);
      }
      current.items.push(item);
      /* Anchor on the largest run so a superscript does not drag the line up. */
      if (item.str.trim().length > 1 && (item.fontSize || 0) >= current.anchorSize) {
        current.anchorSize = item.fontSize || 0;
        current.anchorY = item.y;
      }
    }

    return lines.map(line => {
      line.items.sort((a, b) => a.x - b.x);
      const size = weightedMode(line.items.map(item => [item.fontSize || 0, item.str.length]), 0.5)
        || (line.items[0].fontSize || 10);
      const bodyItems = line.items.filter(item => Math.abs((item.fontSize || 0) - size) <= 0.75);
      const baseline = bodyItems.length ? median(bodyItems.map(item => item.y)) : line.anchorY;
      return {
        items: line.items,
        size,
        baseline,
        x: Math.min(...line.items.map(item => item.x)),
        right: Math.max(...line.items.map(item => item.x + (item.width || 0))),
        bold: bodyItems.length > 0 && bodyItems.every(item => item.bold),
        text: line.items.map(item => item.str).join('').trim()
      };
    });
  }

  /* --------------------- running headers and footers ----------------- */

  const PAGE_NUMBER_RE = new RegExp(
    '^(?:page|sida|sid\\.?|s\\.)?\\s*\\d{1,4}\\s*(?:\\(\\s*\\d{1,4}\\s*\\))?$'
    + '|^\\d{1,4}\\s*\\(\\s*\\d{1,4}\\s*\\)$'
    + '|^[-–—]\\s*\\d{1,4}\\s*[-–—]$', 'i');

  function runningBlockKey(text) {
    return text.toLowerCase().replace(/\d+/g, '#').replace(/\s+/g, ' ').trim();
  }

  /*
    A header repeated on every page is not part of the text. Left in, the report
    title reappears as an uncited heading dozens of times and any rule it
    happens to trip is reported once per page.

    Only lines in the top or bottom band are considered, and only those that
    actually repeat, so a one-off title page or a heading that happens to sit
    high on the page is kept.
  */
  function markRunningBlocks(pages) {
    const seen = new Map();
    const pageCount = pages.length;

    for (const page of pages) {
      const headerLimit = page.height * 0.93;
      const footerLimit = page.height * 0.07;
      for (const line of page.lines) {
        const band = line.baseline >= headerLimit ? 'header'
          : line.baseline <= footerLimit ? 'footer'
          : '';
        line.band = band;
        if (!band || !line.text || line.text.length > 120) continue;
        const key = band + ' ' + runningBlockKey(line.text);
        if (!seen.has(key)) seen.set(key, new Set());
        seen.get(key).add(page.pageNumber);
      }
    }

    let removed = 0;
    for (const page of pages) {
      page.lines = page.lines.filter(line => {
        if (!line.band) return true;
        if (PAGE_NUMBER_RE.test(line.text)) { removed++; return false; }
        const pagesWithLine = seen.get(line.band + ' ' + runningBlockKey(line.text));
        const count = pagesWithLine ? pagesWithLine.size : 0;
        const repeats = count >= 3 || (count >= 2 && count / Math.max(1, pageCount) >= 0.5);
        if (repeats) { removed++; return false; }
        return true;
      });
    }
    return removed;
  }

  /* ----------------------------- columns ----------------------------- */

  /*
    Two-column pages read as nonsense if taken in raw y order - every line of
    the left column interleaves with the line beside it.

    The split has to be found among the items rather than among the lines,
    because the two columns of a page are usually set on a shared grid: their
    baselines coincide, so by the time the items have been grouped into lines
    the columns are already merged and the evidence is gone.

    A gutter is a vertical band that no item overlaps. It has to be near the
    middle, wide enough not to be ordinary word spacing, and have a real share
    of the text on either side.
  */
  function findColumnSplit(items, pageWidth) {
    if (items.length < 20) return null;
    const step = 4;
    const bins = new Array(Math.ceil(pageWidth / step) + 1).fill(0);
    for (const item of items) {
      const from = Math.max(0, Math.floor(item.x / step));
      const to = Math.min(bins.length - 1, Math.floor((item.x + (item.width || 0)) / step));
      for (let bin = from; bin <= to; bin++) bins[bin]++;
    }

    const lowest = Math.floor(pageWidth * 0.32 / step);
    const highest = Math.ceil(pageWidth * 0.68 / step);
    let best = null;
    let runStart = -1;
    for (let bin = lowest; bin <= highest + 1; bin++) {
      const empty = bin <= highest && bins[bin] === 0;
      if (empty && runStart < 0) runStart = bin;
      if (!empty && runStart >= 0) {
        const width = (bin - runStart) * step;
        const centre = (runStart + bin) / 2 * step;
        if (width >= pageWidth * 0.03 && (!best || width > best.width)
            && centre > pageWidth * 0.35 && centre < pageWidth * 0.65) {
          best = { width, split: centre };
        }
        runStart = -1;
      }
    }
    if (!best) return null;

    const left = items.filter(item => item.x + (item.width || 0) <= best.split).length;
    const right = items.length - left;
    const minimum = items.length * 0.2;
    return left >= minimum && right >= minimum ? best.split : null;
  }

  /* --------------------- lines into paragraphs ----------------------- */

  function columnStatistics(lines) {
    const bodySize = weightedMode(lines.map(line => [line.size, line.text.length]), 0.5) || 10;
    const bodyLines = lines.filter(line => Math.abs(line.size - bodySize) <= 0.75);
    const reference = bodyLines.length >= 3 ? bodyLines : lines;
    const gaps = [];
    for (let index = 1; index < reference.length; index++) {
      const gap = reference[index - 1].baseline - reference[index].baseline;
      if (gap > 0 && gap < bodySize * 3) gaps.push(gap);
    }
    const rightEdge = quantile(reference.map(line => line.right), 0.9);
    return {
      bodySize,
      leading: median(gaps) || bodySize * 1.2,
      leftMargin: weightedMode(reference.map(line => [line.x, 1]), 1) || quantile(reference.map(line => line.x), 0.1),
      rightEdge,
      width: Math.max(1, rightEdge - quantile(reference.map(line => line.x), 0.05))
    };
  }

  /*
    Where one paragraph ends and the next begins. Reports use three layouts and
    the checker has to survive all of them:

        block        no indent, extra space between paragraphs
        indented     first line indented, no extra space
        hanging      first line at the margin, continuations indented
                     - this is how every SKB reference list is set

    An indent on its own decides nothing, because the two indented layouts are
    locally identical: both show a line at the margin followed by an indented
    line. What separates them is whether the earlier line ended because it ran
    out of measure or because the paragraph ended, and that has an exact test
    rather than a heuristic one - would the next line's first word have fitted?
    If it would, the break was the author's; if it would not, the line simply
    wrapped and the indent is a continuation.
  */
  /*
    How wide the line's first word is. pdf.js splits a line into items wherever
    the kerning changes, which for some PDFs is once per word and for others
    not at all - so the first item may be a single word or the whole line, and
    taking its width outright would make every line look like a wrap. Where the
    item holds more than one word its width is apportioned by character count:
    only whether the word would have fitted is being decided, not its exact
    setting.
  */
  function firstWordWidth(line) {
    const item = line.items[0];
    if (!item) return 0;
    const width = item.width || 0;
    const word = item.str.match(/^\s*\S+/);
    if (!word || word[0].length >= item.str.length) return width;
    return width * word[0].length / item.str.length;
  }

  function endedDeliberately(line, previous, stats) {
    const space = 0.28 * (previous.size || stats.bodySize || 10);
    return previous.right + space + firstWordWidth(line) < stats.rightEdge - 1;
  }

  function startsNewParagraph(line, previous, stats) {
    if (!previous) return true;

    if (Math.abs(line.size - previous.size) > 0.75) return true;

    const gap = previous.baseline - line.baseline;
    if (gap > stats.leading * 1.45) return true;

    if (!endedDeliberately(line, previous, stats)) return false;

    const atMargin = line.x <= stats.leftMargin + 2;
    const previousIndented = previous.x >= stats.leftMargin + 6;
    if (atMargin && previousIndented) return true;                                   /* hanging indent */
    if (line.x >= previous.x + 6 && previous.x <= stats.leftMargin + 2) return true; /* first-line indent */

    /*
      No indent to go on, so the line's own text has to decide. A line ending
      mid-sentence followed by a lower-case word is a wrap that happened to
      fall short, not a paragraph end.
    */
    const continues = !/[.!?:;,]["'”’)\]]?$/.test(previous.text)
      && /^[a-zåäöü(]/.test(line.text);
    return !continues;
  }

  /*
    A hyphen at a line break may be the typesetter's or the author's. Removing
    the author's turns "cost-benefit" into "costbenefit"; keeping the
    typesetter's turns "radio-active" into a word no rule will match.

    A break hyphen joins two lower-case fragments, so that case is rejoined and
    the rest is kept. The position of every join is recorded either way: the
    caller suppresses dash and spacing findings that land on one, since they
    would be reporting the layout rather than the text.
  */
  function shouldKeepHyphen(before, after) {
    const tail = before.slice(-24).match(/([\p{L}\d]+)-$/u);
    const head = after.match(/^([\p{L}\d]+)/u);
    if (!tail || !head) return true;
    const left = tail[1];
    const right = head[1];
    if (/\d/.test(left) || /\d/.test(right)) return true;
    if (/^\p{Lu}/u.test(right)) return true;
    if (left.length <= 1 || left === left.toUpperCase()) return true;
    return false;
  }

  function assembleParagraph(lines, stats) {
    let text = '';
    const spans = [];
    const joins = [];

    lines.forEach((line, lineIndex) => {
      if (lineIndex > 0) {
        if (/-$/.test(text) && !shouldKeepHyphen(text, line.text)) {
          text = text.slice(0, -1);
          if (spans.length) spans[spans.length - 1].end = Math.min(spans[spans.length - 1].end, text.length);
        } else if (!/\s$/.test(text)) {
          text += ' ';
        }
        joins.push(text.length);
      }

      let previousItem = null;
      for (const item of line.items) {
        const value = normalisePdfText(item.str);
        if (!value) continue;
        /*
          pdf.js splits a word wherever the kerning changes, so the gap between
          runs is the only evidence of a word space. A fifth of an em is wide
          enough to clear kerning and narrow enough to catch a real space.
        */
        if (previousItem && !/\s$/.test(text) && !/^\s/.test(value)) {
          const gap = item.x - (previousItem.x + (previousItem.width || 0));
          if (gap > 0.22 * (line.size || 10)) text += ' ';
        }
        const start = text.length;
        text += value;
        if (text.length > start) {
          spans.push({
            start, end: text.length, inHyperlink: false,
            italic: Boolean(item.italic), bold: Boolean(item.bold),
            underline: false, sup: Boolean(item.sup), sub: Boolean(item.sub)
          });
        }
        previousItem = item;
      }
    });

    /* Offsets are reported against the trimmed text, as the .docx path does. */
    const leading = text.length - text.trimStart().length;
    const trimmed = text.trim();
    const shift = span => ({
      ...span,
      start: Math.max(0, span.start - leading),
      end: Math.max(0, Math.min(trimmed.length, span.end - leading))
    });

    return {
      text: trimmed,
      formatSpans: spans.map(shift).filter(span => span.end > span.start),
      joins: joins.map(offset => offset - leading).filter(offset => offset > 0 && offset < trimmed.length),
      size: lines[0].size,
      bold: lines.every(line => line.bold),
      x: Math.min(...lines.map(line => line.x)),
      baseline: lines[0].baseline,
      lineCount: lines.length,
      bodySize: stats.bodySize
    };
  }

  /* --------------------------- superscripts -------------------------- */

  /*
    1469987 writes a mass number as a superscript and the atom count in a
    formula as a subscript, and the checker reports text where they are missing.
    In a PDF both are ordinary glyphs set smaller and off the baseline, so they
    are recovered by comparing each run with the baseline of its own line.
  */
  function markVerticalAlignment(line) {
    for (const item of line.items) {
      const smaller = (item.fontSize || 0) < line.size * 0.86;
      const offset = item.y - line.baseline;
      item.sup = smaller && offset > line.size * 0.12;
      item.sub = smaller && offset < -line.size * 0.04;
    }
  }

  /* ----------------------------- headings ---------------------------- */

  /*
    headingLevel() in the checker reads Word style names, so the inferred level
    is handed over in that vocabulary - "heading 1" - and every consumer of
    paragraph.style keeps working unchanged.

    Only size and weight are available. Distinct sizes above the body size are
    ranked, largest first; bold text at body size is the lowest heading level a
    report normally uses for a run-in heading.
  */
  function assignHeadingStyles(paragraphs, bodySize) {
    const isShort = paragraph => paragraph.lineCount <= 4 && paragraph.text.length <= 200;
    const sizes = [...new Set(paragraphs
      .filter(paragraph => paragraph.size > bodySize + 0.6 && isShort(paragraph))
      .map(paragraph => Math.round(paragraph.size * 2) / 2))]
      .sort((a, b) => b - a)
      .slice(0, 5);

    for (const paragraph of paragraphs) {
      const rank = sizes.indexOf(Math.round(paragraph.size * 2) / 2);
      if (rank >= 0 && isShort(paragraph)) {
        paragraph.style = 'heading ' + (rank + 1);
      } else if (paragraph.bold && paragraph.lineCount === 1 && paragraph.text.length <= 120
                 && !/[.!?]$/.test(paragraph.text) && paragraph.size >= bodySize - 0.3) {
        paragraph.style = 'heading ' + Math.min(6, sizes.length + 1);
      } else {
        paragraph.style = '';
      }
    }
  }

  /* ----------------------------- footnotes --------------------------- */

  /*
    A footnote is set smaller than the body and sits at the foot of the page.
    It is not excluded from the analysis - footnotes carry citations - but it
    is labelled as an auxiliary region so a finding there is reported as such,
    matching how the .docx path treats word/footnotes.xml.
  */
  function markFootnotes(paragraphs, page, bodySize) {
    const footnoteTop = page.height * 0.22;
    for (const paragraph of paragraphs) {
      paragraph.region = paragraph.size < bodySize - 0.6 && paragraph.baseline < footnoteTop
        ? 'footnote' : 'body';
    }
  }

  /* ---------------------------- the pipeline ------------------------- */

  /**
   * Rebuild a document's paragraphs from the text layer of its pages.
   *
   * @param {Array<{pageNumber:number,width:number,height:number,items:Array}>} rawPages
   *        Each item: { str, x, y, width, fontSize, bold, italic }, with x/y the
   *        left edge and baseline in PDF units, y increasing upwards.
   * @returns {{paragraphs:Array, diagnostics:Object}}
   */
  function reconstructDocument(rawPages) {
    const pages = (rawPages || []).map((page, order) => ({
      pageNumber: page.pageNumber || order + 1,
      width: page.width || 595,
      height: page.height || 842,
      lines: groupIntoLines(page.items || [])
    }));

    const removedRunningLines = markRunningBlocks(pages);

    const allLines = pages.flatMap(page => page.lines);
    const documentBodySize = (allLines.length
      ? weightedMode(allLines.map(line => [line.size, line.text.length]), 0.5)
      : 10) || 10;

    const paragraphs = [];
    let columnPages = 0;

    for (const page of pages) {
      /*
        Column detection needs the items, and running headers have already been
        dropped from the lines, so the items are taken back out of the lines
        that survived. A page found to have two columns is regrouped from
        scratch on each side, since its lines currently span the gutter.
      */
      const bodyItems = page.lines.flatMap(line => line.items);
      const split = findColumnSplit(bodyItems, page.width);
      const columns = split === null ? [page.lines] : [
        groupIntoLines(bodyItems.filter(item => item.x + (item.width || 0) <= split)),
        groupIntoLines(bodyItems.filter(item => item.x + (item.width || 0) > split))
      ];
      if (columns.length > 1) columnPages++;

      for (const columnLines of columns) {
        if (!columnLines.length) continue;
        const stats = columnStatistics(columnLines);
        stats.bodySize = documentBodySize;
        columnLines.forEach(markVerticalAlignment);

        const grouped = [];
        let current = null;
        let previous = null;
        for (const line of columnLines) {
          if (!current || startsNewParagraph(line, previous, stats)) {
            current = [];
            grouped.push(current);
          }
          current.push(line);
          previous = line;
        }

        const pageParagraphs = grouped
          .map(lines => assembleParagraph(lines, stats))
          .filter(paragraph => paragraph.text);
        markFootnotes(pageParagraphs, page, documentBodySize);
        for (const paragraph of pageParagraphs) paragraph.pageNumber = page.pageNumber;
        paragraphs.push(...pageParagraphs);
      }
    }

    assignHeadingStyles(paragraphs, documentBodySize);
    paragraphs.forEach((paragraph, index) => { paragraph.index = index; });

    return {
      paragraphs,
      diagnostics: {
        pageCount: pages.length,
        lineCount: allLines.length,
        paragraphCount: paragraphs.length,
        bodySize: documentBodySize,
        removedRunningLines,
        multiColumnPages: columnPages,
        footnoteParagraphs: paragraphs.filter(paragraph => paragraph.region === 'footnote').length,
        headingParagraphs: paragraphs.filter(paragraph => paragraph.style).length
      }
    };
  }

  /**
   * Convert one pdf.js text-content payload into the item shape above.
   *
   * @param {Object} textContent  result of page.getTextContent()
   * @param {Object} viewport     page.getViewport({ scale: 1 })
   * @param {Function} [fontInfo] fontName -> { bold, italic }
   */
  function itemsFromPdfJs(textContent, viewport, fontInfo) {
    const items = [];
    for (const item of (textContent && textContent.items) || []) {
      if (typeof item.str !== 'string' || !item.str) continue;
      const transform = item.transform || [1, 0, 0, 1, 0, 0];
      /* Rotated or mirrored text is layout decoration, not running text. */
      if (Math.abs(transform[1]) > 0.2 || Math.abs(transform[2]) > 0.2) continue;
      const fontSize = Math.abs(transform[3]) || item.height || 10;
      const font = (fontInfo && fontInfo(item.fontName)) || {};
      items.push({
        str: item.str,
        x: transform[4],
        y: transform[5],
        width: item.width || 0,
        fontSize,
        bold: Boolean(font.bold),
        italic: Boolean(font.italic),
        fontName: item.fontName || ''
      });
    }
    return {
      pageNumber: 0,
      width: viewport ? viewport.width : 595,
      height: viewport ? viewport.height : 842,
      items
    };
  }

  /** Bold and italic as recorded in the embedded font's own name. */
  function fontStyleFromName(name) {
    const value = String(name || '');
    return {
      bold: /bold|black|heavy|semibold|demibold|[-,]bd\b/i.test(value),
      italic: /italic|oblique|[-,]it\b/i.test(value)
    };
  }

  /**
   * Bold and italic for a pdf.js font object.
   *
   * The object carries the flags outright, which is better evidence than its
   * name: a font may be set oblique without saying so in the name, and a name
   * containing "Book" or "Semibold Italic" is easy to read wrongly. The name
   * is the fallback for a font pdf.js could not fully translate.
   */
  function fontStyleFromFont(font, fontName) {
    if (font && (typeof font.italic === 'boolean' || typeof font.bold === 'boolean')) {
      return { bold: Boolean(font.bold), italic: Boolean(font.italic) };
    }
    return fontStyleFromName((font && (font.name || font.loadedName)) || fontName);
  }

  return {
    PDF_CAPABILITIES, DOCX_CAPABILITIES,
    reconstructDocument, itemsFromPdfJs, fontStyleFromName, fontStyleFromFont,
    normalisePdfText,
    /* exported for the geometry tests */
    _internal: {
      groupIntoLines, markRunningBlocks, startsNewParagraph,
      shouldKeepHyphen, columnStatistics, assignHeadingStyles, assembleParagraph, findColumnSplit, endedDeliberately
    }
  };
});
