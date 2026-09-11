/* ==========================================================================
   SKB REFERENCE CHECKER — export

   The rule-summary CSV and the standalone HTML analysis report.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function csvCell(value) {
      const text = String(value ?? '').replace(/\r?\n/g, ' ');
      return `"${text.replace(/"/g, '""')}"`;
    }

    function downloadRuleSummaryCsv() {
      const families = [
        ['Official SKB rule', currentRuleFindings.official || []],
        ['Citation rule', currentRuleFindings.citation || []],
        ['Review rule', currentRuleFindings.review || []]
      ];
      const grouped = new Map();
      for (const [family, items] of families) {
        for (const item of items) {
          const id = item.ruleId || 'unidentified-rule';
          const key = `${family}\u0000${id}\u0000${item.severity || 'review'}`;
          if (!grouped.has(key)) grouped.set(key, {
            family, ruleId: id, ruleName: item.ruleName || item.description || item.issue || id, legacyRuleIds: item.legacyRuleIds || [], severity: item.severity || 'review',
            category: item.category || '', guidance: item.description || item.issue || '',
            occurrences: 0, examples: [], locations: []
          });
          const group = grouped.get(key); group.occurrences++;
          const example = item.fullContext || item.context || item.match || '';
          if (example && group.examples.length < 5 && !group.examples.includes(example)) group.examples.push(example);
          const location = item.location || `${item.sourceLabel || 'Main document'} paragraph ${(item.localIndex ?? item.paragraphIndex ?? item.paraIndex ?? 0) + 1}`;
          if (!group.locations.includes(location)) group.locations.push(location);
        }
      }
      const header = ['Rule name','Rule ID','Legacy rule IDs','Family','Severity','Category','Occurrences','Guidance','Examples','Locations'];
      const rows = [...grouped.values()].sort((a,b)=>b.occurrences-a.occurrences || a.ruleId.localeCompare(b.ruleId)).map(item => [
        item.ruleName,item.ruleId,item.legacyRuleIds.join(' | '),item.family,item.severity,item.category,item.occurrences,item.guidance,item.examples.join(' | '),item.locations.join(' | ')
      ]);
      const csv = '\ufeff' + [header, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n');
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      const baseName = (currentFilename || 'skb-reference-report').replace(/\.(?:docx|pdf)$/i, '').replace(/[^a-z0-9_-]+/gi, '-');
      link.href = url; link.download = `${baseName}-rule-summary.csv`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    }

    function downloadAnalysisReport() {
      if (!results.innerHTML.trim()) return;
      const reportTitle = currentFilename
        ? `SKB Reference Checker — ${currentFilename}`
        : 'SKB Reference Checker report';
      const generated = new Date().toLocaleString();

      /*
        Create a clean copy of the analysis for export. The interactive
        Check Zotero buttons are useful on the live page, but should not
        appear in the downloaded report. Completed Zotero matches remain.
      */
      const exportedResults = results.cloneNode(true);
      exportedResults.querySelectorAll('.rule-summary-filters').forEach(node => node.remove());
      exportedResults.querySelectorAll('.zotero-row-btn').forEach(button => {
        button.remove();
      });
      exportedResults.querySelectorAll('.zotero-inline-results:empty').forEach(container => {
        container.remove();
      });

      const reportHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escHtml(reportTitle)}</title>
<style>
body{max-width:1000px;margin:0 auto;padding:32px;font:15px/1.5 system-ui,sans-serif;color:#222}h1{font-size:1.5rem}small{color:#666}.result-section{margin:16px 0;border:1px solid #ccc;border-radius:8px}.result-section summary{padding:10px 14px;font-weight:700}.section-body{padding:14px}.section-badge{float:right}.ref-table{width:100%;border-collapse:collapse}.ref-table th,.ref-table td{padding:7px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}.ref-key,code,.rule-id,.rule-legacy-id{font-family:monospace}.tag{display:inline-block;margin:3px;padding:3px 8px;border:1px solid #d6a54a;border-radius:12px}a{color:#075fa8}.rule-name{display:block;font-weight:800}.rule-id{display:block;font-size:.75rem;color:#666}.rule-legacy-id{display:block;font-size:.7rem;color:#777}.rule-full-context,.citation-context{white-space:pre-wrap;overflow-wrap:anywhere}.rule-context-match,.citation-context-match{font-weight:800;background:#fff1bd;padding:0 2px;border-radius:3px}.rule-document-group{margin:12px 0;border:1px solid #ddd;border-radius:7px}.rule-document-group>summary{padding:8px;font-weight:800}.rule-document-group-body{padding:8px}.rule-detail-item{padding:9px;margin:8px 0;border:1px solid #ddd;border-radius:6px}.language-intervals{margin-top:7px;padding:7px;border-left:3px solid #aaa}.citation-location-region{display:block;font-weight:700}.citation-location-paragraph{display:block;font-size:.75rem;color:#666}
</style>
</head>
<body>
<h1>${escHtml(reportTitle)}</h1>
<p><small>Generated ${escHtml(generated)}</small></p>
${docInfo.innerHTML}
${exportedResults.innerHTML}
</body>
</html>`;
      const blob = new Blob([reportHtml], { type: 'text/html;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const baseName = (currentFilename || 'skb-reference-report').replace(/\.(?:docx|pdf)$/i, '').replace(/[^a-z0-9_-]+/gi, '-');
      link.href = url;
      link.download = `${baseName}-analysis.html`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }
