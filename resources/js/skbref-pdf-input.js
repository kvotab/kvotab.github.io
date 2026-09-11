/* ==========================================================================
   SKB REFERENCE CHECKER — pdf-input

   Reading a PDF: loading pdf.js with an integrity check, extracting each
   page's text and fonts, and the notice saying what a PDF cannot carry.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    let currentFile = null;
    let currentFormat = 'docx';

    /* ─────────────────────────── PDF INPUT ─────────────────────────── */

    /*
      pdf.js is pinned to the last release that ships a UMD build, because this
      page is a plain script with no bundler and cdnjs carries only ES modules
      for 4.x and later. Text extraction is the part of the API that has stayed
      the same throughout, and the alternative — a dynamic import() — cannot
      carry an integrity hash, which the JSZip tag in the head sets the pattern
      for. Both hashes below were checked against the served bytes.
    */
    const PDFJS_VERSION = '3.11.174';
    const PDFJS_BASE = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${PDFJS_VERSION}/`;
    const PDFJS_INTEGRITY = {
      'pdf.min.js': 'sha512-q+4liFwdPC/bNdhUpZx6aXDx/h77yEQtn4I1slHydcbZK34nLaR3cAeYSJshoxIOq3mjEf7xJE8YWIUHMn+oCQ==',
      'pdf.worker.min.js': 'sha512-BbrZ76UNZq5BhH7LL7pn9A4TKQpQeNCHOo65/akfelcIBbcVvYWOFQKPXIrykE3qZxYjmDX573oa4Ywsc7rpTw=='
    };
    let pdfjsPromise = null;

    function loadScriptWithIntegrity(url, integrity) {
      return new Promise((resolve, reject) => {
        const element = document.createElement('script');
        element.src = url;
        element.integrity = integrity;
        element.crossOrigin = 'anonymous';
        element.onload = () => resolve();
        element.onerror = () => reject(new Error(`Could not load ${url}`));
        document.head.appendChild(element);
      });
    }

    /*
      The worker cannot be started straight from the CDN, because a classic
      Worker script must be same-origin. It is fetched, checked against the same
      hash a script tag would have enforced, and started from a blob — keeping
      integrity rather than trading it for a working worker.

      The worker is constructed here and handed to pdf.js as a port, rather than
      giving pdf.js the blob URL to open itself. That matters: given a URL it
      considers cross-origin, pdf.js wraps it in a second blob that calls
      importScripts() on the first. On a page opened from the filesystem the
      blob URL is `blob:null/...`, and a worker started from a blob cannot
      importScripts a null-origin blob — so the worker died on every PDF with

          Failed to execute 'importScripts' on 'WorkerGlobalScope'
          The script at 'blob:null/...' failed to load

      pdf.js recovered by parsing on the main thread, so the analysis was right
      and only the speed and the alarming error were wrong. Constructing the
      worker directly avoids the wrapper, and works both from a server and from
      a file:// page.
    */
    async function createPdfWorker() {
      const name = 'pdf.worker.min.js';
      const response = await fetch(PDFJS_BASE + name, { mode: 'cors' });
      if (!response.ok) throw new Error(`Could not load ${name} (HTTP ${response.status})`);
      const bytes = await response.arrayBuffer();
      const digest = await crypto.subtle.digest('SHA-512', bytes);
      const encoded = 'sha512-' + btoa(String.fromCharCode(...new Uint8Array(digest)));
      if (encoded !== PDFJS_INTEGRITY[name]) {
        throw new Error(`${name} did not match its expected integrity hash and was not run.`);
      }
      const worker = new Worker(URL.createObjectURL(new Blob([bytes], { type: 'text/javascript' })));
      /*
        Handled here so it cannot reach window.onerror. A worker that dies is a
        loss of speed, not of correctness — pdf.js carries on by parsing on the
        main thread — and telling the reader the page has stopped working would
        be false.
      */
      worker.onerror = event => {
        ignoreFailure('pdf-worker', new Error(event.message || 'worker failed; parsing on the main thread'));
      };
      return worker;
    }

    function loadPdfJs() {
      if (!pdfjsPromise) {
        pdfjsPromise = (async () => {
          await loadScriptWithIntegrity(PDFJS_BASE + 'pdf.min.js', PDFJS_INTEGRITY['pdf.min.js']);
          const library = window.pdfjsLib;
          if (!library) throw new Error('pdf.js loaded but did not register itself.');
          try {
            library.GlobalWorkerOptions.workerPort = await createPdfWorker();
          } catch (error) {
            /* Without a worker pdf.js parses on the main thread: slower on a
               long report, but the text it produces is the same. */
            ignoreFailure('pdf-worker-setup', error);
            library.GlobalWorkerOptions.workerPort = null;
            library.GlobalWorkerOptions.workerSrc = '';
          }
          return library;
        })().catch(error => { pdfjsPromise = null; throw error; });
      }
      return pdfjsPromise;
    }

    /*
      Bold and italic live in the embedded fonts, and pdf.js publishes those to
      page.commonObjs — but only while building an operator list, not while
      extracting text. So the operator list is requested first and thrown away;
      without it every font lookup misses and every italic run reads as
      upright, which would make the rule wanting quantity symbols italic report
      each correct one as an error.
    */
    async function loadPdfPageFonts(page) {
      try {
        await page.getOperatorList();
        return true;
      } catch (error) {
        /* Some PDFs have content streams pdf.js cannot walk. The text is still
           extractable; only the character styles are lost. */
        console.warn(`Could not read the fonts on page ${page.pageNumber}.`, error);
        return false;
      }
    }

    function pdfFontResolver(page, counters) {
      const cache = new Map();
      return name => {
        if (cache.has(name)) return cache.get(name);
        let style = { bold: false, italic: false };
        try {
          if (page.commonObjs.has(name)) {
            style = SkbPdf.fontStyleFromFont(page.commonObjs.get(name), name);
            counters.resolved++;
          } else {
            style = SkbPdf.fontStyleFromName(name);
            counters.missing++;
          }
        } catch (error) {
          style = SkbPdf.fontStyleFromName(name);
          counters.missing++;
        }
        cache.set(name, style);
        return style;
      };
    }

    async function readPdfDocument(file) {
      if (!window.SkbPdf) throw new Error('resources/js/skb-pdf.js did not load.');
      showStatus('Loading the PDF reader…');
      const pdfjs = await loadPdfJs();
      setProgress(10);
      showStatus('Opening the PDF…');
      const pdf = await pdfjs.getDocument({
        data: new Uint8Array(await file.arrayBuffer()),
        isEvalSupported: false
      }).promise;

      const rawPages = [];
      const fonts = { resolved: 0, missing: 0, pagesWithFonts: 0 };
      let textItems = 0;
      for (let number = 1; number <= pdf.numPages; number++) {
        const page = await pdf.getPage(number);
        if (await loadPdfPageFonts(page)) fonts.pagesWithFonts++;
        const textContent = await page.getTextContent();
        const normalised = SkbPdf.itemsFromPdfJs(
          textContent, page.getViewport({ scale: 1 }), pdfFontResolver(page, fonts));
        normalised.pageNumber = number;
        textItems += normalised.items.length;
        rawPages.push(normalised);
        page.cleanup();
        if (number % 5 === 0 || number === pdf.numPages) {
          setProgress(10 + Math.round(22 * number / pdf.numPages));
          showStatus(`Reading page ${number} of ${pdf.numPages}…`);
          await yieldToBrowser();
        }
      }

      /*
        A scanned PDF carries images and no text layer. Analysing it would
        report a document with no references and no citations, which reads as a
        clean bill of health rather than as a file that cannot be checked.
      */
      if (!textItems) {
        throw new Error('This PDF has no text layer — it is most likely a scan. '
          + 'Run optical character recognition on it first, or upload the .docx.');
      }

      showStatus('Rebuilding paragraphs…');
      await yieldToBrowser();
      const { paragraphs: rebuilt, diagnostics } = SkbPdf.reconstructDocument(rawPages);
      /*
        If not one font could be read, italic and bold are not merely sparse —
        they are absent, and the checks that read them have to be switched off
        rather than reporting every correct occurrence.
      */
      diagnostics.fontsResolved = fonts.resolved;
      diagnostics.fontLookupsMissed = fonts.missing;
      diagnostics.characterStyles = fonts.resolved > 0;
      console.info('PDF reconstruction', diagnostics);

      const main = [];
      const auxiliary = [];
      for (const paragraph of rebuilt) {
        const language = classifyParagraphLanguage(paragraph.text, { counts: {} });
        const converted = {
          text: paragraph.text,
          fields: [],                 /* a PDF carries no field codes */
          formatSpans: paragraph.formatSpans,
          hasZoteroBibliography: false,
          joins: paragraph.joins,
          style: paragraph.style,
          isInTable: false, tableDepth: 0, numId: '',
          pageNumber: paragraph.pageNumber,
          language: language.language, languageConfidence: language.confidence,
          languageSource: language.source, languageEvidence: language.evidence,
          languageRanges: []
        };
        (paragraph.region === 'footnote' ? auxiliary : main).push(converted);
      }

      /* Locations read as "Page 12 paragraph 3", which is what a reader of the
         PDF itself can actually navigate to. */
      const perPage = new Map();
      const label = paragraph => {
        const count = perPage.get(paragraph.pageNumber) || 0;
        perPage.set(paragraph.pageNumber, count + 1);
        paragraph.localIndex = count;
        paragraph.sourcePart = `pdf/page-${paragraph.pageNumber}`;
        paragraph.sourceLabel = `Page ${paragraph.pageNumber}`;
      };
      main.forEach((paragraph, index) => { paragraph.index = index; label(paragraph); });
      auxiliary.forEach((paragraph, index) => {
        paragraph.index = main.length + index;
        label(paragraph);
        paragraph.documentRegion = 'auxiliary';
        paragraph.regionLabel = `Footnote, page ${paragraph.pageNumber}`;
        paragraph.sourceLabel = paragraph.regionLabel;
      });

      let section = '';
      for (const paragraph of main) {
        if (headingLevel(paragraph.style) && paragraph.text) section = paragraph.text;
        paragraph.section = section;
      }

      return { paragraphs: main, auxiliaryParagraphs: auxiliary, diagnostics };
    }

    /*
      Everything the PDF path cannot check, stated on the page. A checker that
      quietly skips a rule is worse than one that never had it: the reader has
      no way of knowing the report was not checked for it.
    */
    function renderFormatNotice(diagnostics) {
      const notice = $('format-notice');
      if (!diagnostics) {
        notice.classList.remove('show');
        notice.innerHTML = '';
        return;
      }
      const rebuilt = [
        `${diagnostics.paragraphCount} paragraphs rebuilt from ${diagnostics.lineCount} lines on ${diagnostics.pageCount} page(s)`,
        `${diagnostics.headingParagraphs} heading(s) inferred from type size`,
        `${diagnostics.removedRunningLines} running header/footer line(s) removed`
      ];
      if (diagnostics.multiColumnPages) rebuilt.push(`${diagnostics.multiColumnPages} two-column page(s)`);
      if (diagnostics.fontsResolved) rebuilt.push(`${diagnostics.fontsResolved} font(s) read for italic and bold`);
      if (diagnostics.footnoteParagraphs) rebuilt.push(`${diagnostics.footnoteParagraphs} footnote paragraph(s)`);
      notice.innerHTML = `<strong>Read as PDF.</strong> ${escHtml(rebuilt.join(' · '))}.
        A PDF records positions rather than structure, so these checks are switched off
        instead of being guessed at:
        <ul>
          <li><strong>Non-breaking spaces</strong> — a PDF cannot distinguish one from an
              ordinary space, so the hard-space rules for %, °C and unit symbols are not applied.</li>
          <li><strong>Underlining</strong> — drawn as a graphic, not recorded as a text attribute.</li>
          <li><strong>Zotero field codes</strong> — citations are read as plain text, so one
              inserted with Zotero cannot be told from one typed by hand.</li>
          <li><strong>Table cells</strong> — text set in a table is analysed as running text.</li>
          ${diagnostics.characterStyles ? '' : '<li><strong>Italic and bold</strong> — no font could be read from this PDF, so the check that quantity symbols are italic is not applied.</li>'}
        </ul>
        Headings, paragraph boundaries and the reference list are reconstructed from the
        layout. For the complete check, upload the .docx.`;
      notice.classList.add('show');
    }

    /* Reloading a rule pack changes the findings, so re-run the last document. */
    async function reanalyseCurrentDocument() {
      if (!currentFile) return;
      await handleFile(currentFile);
    }
