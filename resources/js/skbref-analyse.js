/* ==========================================================================
   SKB REFERENCE CHECKER — analyse

   handleFile — the pipeline both formats run through, from the dropped
   file to the rendered report.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    async function handleFile(file) {
      const lowered = file.name.toLowerCase();
      const isPdf = lowered.endsWith('.pdf');
      if (!isPdf && !lowered.endsWith('.docx')) {
        notifyUser('This page reads .docx and .pdf reports. Choose one of those.');
        return;
      }
      /*
        The file is read into memory in full, so a mis-dragged archive used to
        give no error and no progress — just a tab that stopped responding.
      */
      const size = kvotFileTooLarge(file);
      if (size.tooLarge) {
        notifyUser(size.reason);
        return;
      }
      currentFile = file;
      currentFormat = isPdf ? 'pdf' : 'docx';
      dropzone.style.display = 'none';
      currentFilename = file.name;
      setProgress(5);
      showStatus('Reading file…');
      /* The notice describes the document on screen. Clear it before reading a
         new one, or a file that fails to open leaves the previous file's notice
         standing over an error message. */
      renderFormatNotice(null);
      try {
        let paragraphs;
        let auxiliaryParagraphs;
        let capabilities = FULL_CAPABILITIES;
        let pdfDiagnostics = null;
        if (isPdf) {
          const read = await readPdfDocument(file);
          paragraphs = read.paragraphs;
          auxiliaryParagraphs = read.auxiliaryParagraphs;
          pdfDiagnostics = read.diagnostics;
          capabilities = { ...FULL_CAPABILITIES, ...SkbPdf.PDF_CAPABILITIES,
            'character-styles': pdfDiagnostics.characterStyles };
        } else {
          const zip = await JSZip.loadAsync(await file.arrayBuffer());
          setProgress(15);
          showStatus('Unzipping .docx…');
          const docXml = await zip.file('word/document.xml')?.async('string');
          const stylesXml = await zip.file('word/styles.xml')?.async('string') || '';
          const auxiliaryPartNames = Object.keys(zip.files).filter(name => /^word\/(?:footnotes|endnotes|comments|header\d+|footer\d+)\.xml$/i.test(name));
          if (!docXml) throw new Error('word/document.xml not found — is this a valid .docx?');
          setProgress(30);
          showStatus('Parsing document…');
          await yieldToBrowser();
          const mainParsed = parseDocXml(docXml, stylesXml);
          paragraphs = mainParsed.paragraphs;
          paragraphs.forEach((paragraph,index)=>{paragraph.index=index;paragraph.localIndex=index;paragraph.sourcePart='word/document.xml';paragraph.sourceLabel='Main document';});
          auxiliaryParagraphs=[];
          for(const partName of auxiliaryPartNames){const xml=await zip.file(partName).async('string'),parsed=parseDocXml(xml,stylesXml),base=paragraphs.length+auxiliaryParagraphs.length,label=/footnotes/i.test(partName)?'Footnotes':/endnotes/i.test(partName)?'Endnotes':/comments/i.test(partName)?'Comments':/header(\d+)/i.test(partName)?`Header ${partName.match(/header(\d+)/i)[1]}`:`Footer ${partName.match(/footer(\d+)/i)?.[1]||''}`;parsed.paragraphs.forEach((paragraph,index)=>{paragraph.localIndex=index;paragraph.index=base+index;paragraph.sourcePart=partName;paragraph.sourceLabel=label;paragraph.documentRegion='auxiliary';paragraph.regionLabel=label;});auxiliaryParagraphs.push(...parsed.paragraphs);}
        }
        renderFormatNotice(pdfDiagnostics);
        const allParagraphs=[...paragraphs,...auxiliaryParagraphs];
        const languageProfile=calculateDocumentLanguage(allParagraphs),isSwedish=languageProfile.language==='sv';
        setProgress(42);
        showStatus('Finding reference list…');
        await yieldToBrowser();
        const { refListParagraphs, bodyParagraphs, refListStart, refListEnd } = splitAtRefList(paragraphs);
        /*
          Mark the reference list before any rule runs. Terminology preferences
          apply to what SKB writes, not to the titles of the works being cited,
          which must be reproduced exactly as published.
        */
        for (const paragraph of refListParagraphs) paragraph.isReferenceList = true;
        setProgress(45);
        showStatus('Applying rules…');
        await yieldToBrowser();
        let forbiddenMatches = findForbiddenWordMatches(allParagraphs);
        let officialWritingIssues = findOfficialSkbTextIssues(allParagraphs, languageProfile, capabilities);
        officialWritingIssues.push(...findFormattingIssues(allParagraphs, capabilities));
        let potentialInvalidCitations = findPotentialInvalidCitations([...bodyParagraphs, ...auxiliaryParagraphs]);
        console.info('Reference-list detection', {
          totalParagraphCount: paragraphs.length,
          refListStart,
          refListEnd,
          referenceParagraphCount: refListParagraphs.length,
          paragraphsAroundStart: paragraphs
            .slice(Math.max(0, refListStart - 3), refListStart + 8)
            .map((item, offset) => ({
              index: Math.max(0, refListStart - 3) + offset,
              style: item.style,
              text: item.text
            })),
          firstReferenceParagraphs: refListParagraphs.slice(0, 8).map(item => item.text)
        });
        setProgress(58);
        showStatus('Extracting references…');
        await yieldToBrowser();
        const refEntries = extractRefEntries(refListParagraphs);
        officialWritingIssues.push(
          ...findOfficialSkbReferenceIssues(refEntries, refListParagraphs, isSwedish, capabilities),
          ...findReferenceListOrderIssues(refEntries),
          ...findYearSuffixIssues(refEntries)
        );
        const deduplicatedFindings = deduplicateRuleFindings(officialWritingIssues, potentialInvalidCitations, forbiddenMatches);
        officialWritingIssues = deduplicatedFindings.official;
        potentialInvalidCitations = deduplicatedFindings.citation;
        forbiddenMatches = deduplicatedFindings.review;
        currentRuleFindings = {
          official: officialWritingIssues,
          citation: potentialInvalidCitations,
          review: forbiddenMatches
        };
        setProgress(70);
        showStatus('Finding in-text citations…');
        await yieldToBrowser();
        const inTextCites = findInTextCites([...bodyParagraphs, ...auxiliaryParagraphs], refEntries);
        setProgress(82);
        showStatus('Cross-referencing…');
        await yieldToBrowser();
        const report = attachOrphanSuggestions(crossReference(refEntries, inTextCites));
        currentReport = report;
        currentRefEntries = refEntries;
        setProgress(92);
        showStatus('Checking SKB format rules…');
        await yieldToBrowser();
        const formatIssues = checkSkbFormat(refEntries);
        for (const duplicates of report.duplicateKeys) {
          for (const entry of duplicates) {
            formatIssues.push({
              key: entry.key,
              issue: `Duplicate key in reference list — ${duplicates.length} entries share the same key`,
              severity: 'error'
            });
          }
        }
        setProgress(100);
        hideStatus();
        setTimeout(hideProgress, 450);
        renderResults(file.name, refEntries, inTextCites, report, formatIssues, forbiddenMatches, potentialInvalidCitations, officialWritingIssues, allParagraphs.length, refListStart, isSwedish, languageProfile);
      } catch (error) {
        hideStatus();
        hideProgress();
        results.innerHTML = `<div style="color:var(--color-kvot-accent);padding:16px;background:var(--bg-secondary);border:1px solid var(--color-kvot-accent);border-radius:8px"><strong>Error:</strong> ${escHtml(error.message)}</div>`;
        resetBtn.classList.add('show');
      }
    }
