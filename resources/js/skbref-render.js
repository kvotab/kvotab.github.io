/* ==========================================================================
   SKB REFERENCE CHECKER — render

   Turning a finished analysis into the page: the summary cards, the rule
   findings and every result section.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function findForbiddenWordMatches(paragraphs) {
      const matches = [];
      const reviewRules = activeReviewRules();
      for (let ruleIndex = 0; ruleIndex < reviewRules.length; ruleIndex++) {
        const rule = reviewRules[ruleIndex];
        if (!rule.enabled) continue;
        let expression;
        try {
          expression = new RegExp(rule.pattern, rule.flags || 'gu');
        } catch (error) {
          console.warn('Invalid review-rule regular expression:', rule.pattern, error);
          continue;
        }
        for (const paragraph of paragraphs) {
          /*
            Terminology preferences describe how SKB writes, so they do not
            apply to the reference list, where the titles of cited works must
            be reproduced exactly as published.
          */
          if (paragraph.isReferenceList) continue;
          const text = paragraph.text || '';
          expression.lastIndex = 0;
          let match;
          while ((match = expression.exec(text)) !== null) {
            const localLanguage = languageAtRange(paragraph, match.index, match.index + match[0].length);
            if (rule.language && ['sv','en'].includes(localLanguage.language) && localLanguage.confidence >= .6 && rule.language !== localLanguage.language) continue;
            if (rule.custom === 'require-ab-prefix') {
              const prefix = text.slice(Math.max(0, match.index - 12), match.index).replace(/[\s\u00a0]+$/u, ' ').trimEnd();
              if (/\bAB$/u.test(prefix)) continue;
            }
            const start = Math.max(0, match.index - 55);
            const end = Math.min(text.length, match.index + match[0].length + 55);
            matches.push({
              ruleIndex,
              ruleId: rule.id,
              ruleName: rule.label,
              legacyRuleIds: rule.legacyIds || [],
              packName: rule.packName || BUILT_IN_PACK_NAME,
              category: rule.category,
              severity: rule.severity,
              pattern: rule.pattern,
              description: rule.description,
              match: match[0],
              matchStart: match.index,
              matchEnd: match.index + match[0].length,
              paragraphIndex: paragraph.index,
              localIndex: paragraph.localIndex,
              sourcePart: paragraph.sourcePart,
              sourceLabel: paragraph.sourceLabel || 'Main document',
              section: paragraph.section || '',
              context: `${start > 0 ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`,
              fullContext: text,
              language: languageAtRange(paragraph, match.index, match.index + match[0].length).language,
              languageConfidence: languageAtRange(paragraph, match.index, match.index + match[0].length).confidence,
              languageRanges: paragraph.languageRanges || []
            });
            if (match[0].length === 0) expression.lastIndex++;
          }
        }
      }
      return matches;
    }

    function renderRuleContext(item){const text=String(item?.fullContext||item?.context||item?.match||'');if(!text)return'';let start=Number.isFinite(item?.matchStart)?item.matchStart:-1,end=Number.isFinite(item?.matchEnd)?item.matchEnd:-1;if(!item?.fullContext||start<0||end<=start||end>text.length){const literal=String(item?.match||'');start=literal?text.indexOf(literal):-1;end=start>=0?start+literal.length:-1;}if(start<0||end<=start||end>text.length)return escHtml(text);return `${escHtml(text.slice(0,start))}<strong class="rule-context-match">${escHtml(text.slice(start,end))}</strong>${escHtml(text.slice(end))}`;}

    function findingAnchorId(item, family = 'rule') {
      const part = stableRuleHash(item.sourcePart || item.sourceLabel || 'main');
      const paragraph = item.localIndex ?? item.paragraphIndex ?? item.paraIndex ?? 0;
      const start = Number.isFinite(item.matchStart) ? item.matchStart : 0;
      return `finding-${family}-${part}-${paragraph}-${start}-${stableRuleHash(item.ruleId || item.description || item.match || '')}`;
    }

    function findingLocationLabel(item) {
      const label = item.sourceLabel || (item.sourcePart && item.sourcePart !== 'word/document.xml' ? item.sourcePart : 'Main document');
      const paragraph = (item.localIndex ?? item.paragraphIndex ?? item.paraIndex ?? 0) + 1;
      return `${label}, paragraph ${paragraph}${item.section && item.section !== label ? ` · ${item.section}` : ''}`;
    }

    function findingLocationLink(item, family) {
      const id = findingAnchorId(item, family);
      return `<a class="rule-location-link" href="#${escHtml(id)}" title="Jump to this finding in the results">${escHtml(findingLocationLabel(item))}</a>`;
    }

    function handleRuleLocationClick(event) {
      const link = event.target.closest('.rule-location-link');
      if (!link) return;
      const id = decodeURIComponent(link.getAttribute('href') || '').replace(/^#/, '');
      const target = id ? document.getElementById(id) : null;
      if (!target) return;
      event.preventDefault();
      let details = target.closest('details');
      while (details) {
        details.open = true;
        details = details.parentElement?.closest('details');
      }
      history.replaceState(null, '', `#${id}`);
      requestAnimationFrame(() => target.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    }

    function handleRuleSummaryFilter(event) {
      const summarySelect = event.target.closest('[data-rule-summary-filter]');
      if (summarySelect) {
        const container = summarySelect.closest('.rule-summary-container');
        if (!container) return;
        const family = container.querySelector('[data-rule-summary-filter="family"]')?.value || 'all';
        const severity = container.querySelector('[data-rule-summary-filter="severity"]')?.value || 'all';
        let shown = 0;
        container.querySelectorAll('.rule-summary-row').forEach(row => {
          row.hidden = !((family === 'all' || row.dataset.family === family) && (severity === 'all' || row.dataset.severity === severity));
          if (!row.hidden) shown++;
        });
        const count = container.querySelector('.rule-filter-count');
        if (count) count.textContent = `${shown} rule(s) shown`;
        return;
      }

      const detailSelect = event.target.closest('[data-rule-detail-filter]');
      if (!detailSelect) return;
      const container = detailSelect.closest('.rule-detail-container');
      if (!container) return;
      const severity = container.querySelector('[data-rule-detail-filter="severity"]')?.value || 'all';
      const ruleId = container.querySelector('[data-rule-detail-filter="rule"]')?.value || 'all';
      const part = container.querySelector('[data-rule-detail-filter="part"]')?.value || 'all';
      let shown = 0;
      container.querySelectorAll('.rule-detail-item').forEach(item => {
        item.hidden = !((severity === 'all' || item.dataset.severity === severity) &&
          (ruleId === 'all' || item.dataset.ruleId === ruleId) &&
          (part === 'all' || item.dataset.part === part));
        if (!item.hidden) shown++;
      });
      container.querySelectorAll('.rule-document-group').forEach(group => {
        const visible = [...group.querySelectorAll('.rule-detail-item')].some(item => !item.hidden);
        group.hidden = !visible;
        if (visible) group.open = true;
      });
      const count = container.querySelector('.rule-detail-filter-count');
      if (count) count.textContent = `${shown} finding(s) shown`;
    }

    function ruleDocumentPartKey(item) {
      return item.sourcePart || item.sourceLabel || 'word/document.xml';
    }

    function ruleDocumentPartLabel(item) {
      if (item.sourceLabel) return item.sourceLabel;
      const part = item.sourcePart || 'word/document.xml';
      if (part === 'word/document.xml') return 'Main document';
      if (/footnotes\.xml$/i.test(part)) return 'Footnotes';
      if (/endnotes\.xml$/i.test(part)) return 'Endnotes';
      if (/comments\.xml$/i.test(part)) return 'Comments';
      const header = part.match(/header(\d+)\.xml$/i); if (header) return `Header ${header[1]}`;
      const footer = part.match(/footer(\d+)\.xml$/i); if (footer) return `Footer ${footer[1]}`;
      return part;
    }

    function buildRuleDetailFilters(items) {
      const severities = [...new Set(items.map(item => item.severity || 'review'))].sort();
      const rules = [...new Set(items.map(item => item.ruleId || 'unidentified-rule'))].sort();
      const parts = [...new Map(items.map(item => [ruleDocumentPartKey(item), ruleDocumentPartLabel(item)])).entries()]
        .sort((a,b) => a[1].localeCompare(b[1]));
      return `<div class="rule-summary-filters">
        <label>Document part<select data-rule-detail-filter="part"><option value="all">All document parts</option>${parts.map(([value,label]) => `<option value="${escHtml(value)}">${escHtml(label)}</option>`).join('')}</select></label>
        <label>Severity<select data-rule-detail-filter="severity"><option value="all">All severities</option>${severities.map(value => `<option value="${escHtml(value)}">${escHtml(value)}</option>`).join('')}</select></label>
        <label>Rule ID<select data-rule-detail-filter="rule"><option value="all">All rule IDs</option>${rules.map(value => `<option value="${escHtml(value)}">${escHtml(value)}</option>`).join('')}</select></label>
        <span class="rule-detail-filter-count">${items.length} finding(s) shown</span>
      </div>`;
    }

    function buildGroupedRuleDetails(items, family, renderItem) {
      const groups = new Map();
      for (const item of items) {
        const key = ruleDocumentPartKey(item);
        if (!groups.has(key)) groups.set(key, { key, label: ruleDocumentPartLabel(item), items: [] });
        groups.get(key).items.push(item);
      }
      return [...groups.values()].sort((a,b) => a.label.localeCompare(b.label)).map(group => `
        <details class="rule-document-group" data-part="${escHtml(group.key)}" open>
          <summary>${escHtml(group.label)} · ${group.items.length} finding(s)</summary>
          <div class="rule-document-group-body">${group.items.map(item => renderItem(item, family, group.key)).join('')}</div>
        </details>`).join('');
    }

    function buildRuleFindingSummary(officialIssues, citationIssues, reviewMatches) {
      const all = [
        ...officialIssues.map(item => ({ ...item, family: 'Official SKB rule', familyKey: 'official', detailFamily: 'official' })),
        ...citationIssues.map(item => ({ ...item, family: 'Citation rule', familyKey: 'citation', detailFamily: 'citation' })),
        ...reviewMatches.map(item => ({ ...item, family: 'Review rule', familyKey: 'review', detailFamily: 'review' }))
      ];
      if (!all.length) return section('Rule findings summary', 0, '<p class="empty-notice">No rule findings were detected.</p>');
      const byRule = new Map(), bySeverity = new Map();
      for (const item of all) {
        const id = item.ruleId || 'unidentified-rule';
        const key = `${item.familyKey}\u0000${id}\u0000${item.severity || 'review'}`;
        if (!byRule.has(key)) byRule.set(key, { id, name:item.ruleName||item.description||item.issue||id, legacyIds:item.legacyRuleIds||[], severity: item.severity || 'review', family: item.family, familyKey: item.familyKey, description: item.description || item.issue || '', count: 0, examples: [] });
        const ruleGroup = byRule.get(key); ruleGroup.count++;
        if (ruleGroup.examples.length < 3) ruleGroup.examples.push(item);
        const severity = item.severity || 'review';
        bySeverity.set(severity, (bySeverity.get(severity) || 0) + 1);
      }
      const familyOptions = [['all','All families'],['official','Official SKB rule'],['citation','Citation rule'],['review','Review rule']];
      const severities = [...new Set([...byRule.values()].map(item => item.severity))].sort();
      const filters = `<div class="rule-summary-filters">
        <label>Rule family<select data-rule-summary-filter="family">${familyOptions.map(([value,label]) => `<option value="${value}">${label}</option>`).join('')}</select></label>
        <label>Severity<select data-rule-summary-filter="severity"><option value="all">All severities</option>${severities.map(value => `<option value="${escHtml(value)}">${escHtml(value)}</option>`).join('')}</select></label>
        <span class="rule-filter-count">${byRule.size} rule(s) shown</span>
      </div>`;
      const severityTags = [...bySeverity].sort((a,b)=>a[0].localeCompare(b[0])).map(([severity,count]) => `<span class="tag">${escHtml(severity)}: <strong>${count}</strong></span>`).join('');
      const rows = [...byRule.values()].sort((a,b)=>b.count-a.count || a.id.localeCompare(b.id)).map(item => `<tr class="rule-summary-row" data-family="${escHtml(item.familyKey)}" data-severity="${escHtml(item.severity)}"><td><span class="rule-name">${escHtml(item.name)}</span><span class="rule-id">${escHtml(item.id)}</span>${item.legacyIds.length?`<span class="rule-legacy-id">Legacy: ${escHtml(item.legacyIds.join(', '))}</span>`:''}</td><td>${escHtml(item.family)}</td><td>${escHtml(item.severity)}</td><td class="cite-count">${item.count}</td><td>${escHtml(item.description)}</td><td>${item.examples.map(example => `<div class="rule-full-context">${renderRuleContext(example)}</div><div>${findingLocationLink(example, example.detailFamily)}</div>`).join('')}</td></tr>`).join('');
      return section('Rule findings summary', byRule.size, `<div class="rule-summary-container">${filters}<div class="tag-list" style="margin-bottom:12px">${severityTags}</div><table class="ref-table"><thead><tr><th>Rule name / ID</th><th>Family</th><th>Severity</th><th>Occurrences</th><th>Guidance</th><th>Examples and locations</th></tr></thead><tbody>${rows}</tbody></table></div>`, false);
    }

    function buildForbiddenWordsSection(matches) {
      if (!matches.length) return section('Words and expressions to review', 0,
        '<p class="empty-notice">No enabled review patterns matched the document text.</p>');
      const grouped = new Map(), severityCounts = new Map();
      for (const item of matches) {
        severityCounts.set(item.severity || 'review', (severityCounts.get(item.severity || 'review') || 0) + 1);
        const key = item.ruleId || `${item.pattern}\u0000${item.description}`;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(item);
      }
      const ruleSummaryRows = [...grouped.values()].map(items => ({
        ruleId: items[0].ruleId || 'unidentified-rule', ruleName:items[0].ruleName||items[0].description, legacyIds:items[0].legacyRuleIds||[], severity: items[0].severity || 'review', count: items.length,
        description: items[0].description, examples: items.slice(0,3)
      })).sort((a,b)=>b.count-a.count || a.ruleId.localeCompare(b.ruleId));
      const severitySummary = [...severityCounts].sort((a,b)=>a[0].localeCompare(b[0])).map(([severity,count]) => `<span class="tag">${escHtml(severity)}: <strong>${count}</strong></span>`).join('');
      const ruleSummary = `<details style="margin-bottom:14px"><summary style="cursor:pointer;font-weight:700">Summary by rule ID and severity</summary>
        <div class="tag-list" style="margin:10px 0">${severitySummary}</div>
        <table class="ref-table"><thead><tr><th>Rule name / ID</th><th>Severity</th><th>Occurrences</th><th>Guidance</th><th>Examples</th></tr></thead><tbody>${ruleSummaryRows.map(item => `<tr><td><span class="rule-name">${escHtml(item.ruleName)}</span><span class="rule-id">${escHtml(item.ruleId)}</span>${item.legacyIds.length?`<span class="rule-legacy-id">Legacy: ${escHtml(item.legacyIds.join(', '))}</span>`:''}</td><td>${escHtml(item.severity)}</td><td class="cite-count">${item.count}</td><td>${escHtml(item.description)}</td><td>${item.examples.map(example => `<div class="rule-full-context">${renderRuleContext(example)}</div><div>${findingLocationLink(example,'review')}</div>`).join('')}</td></tr>`).join('')}</tbody></table></details>`;
      const details = buildGroupedRuleDetails(matches, 'review', item => `
        <article id="${findingAnchorId(item, 'review')}" class="rule-detail-item rule-finding-row" data-part="${escHtml(ruleDocumentPartKey(item))}" data-severity="${escHtml(item.severity || 'review')}" data-rule-id="${escHtml(item.ruleId || 'unidentified-rule')}">
          <div class="rule-detail-head"><span class="forbidden-match">${escHtml(item.match)}</span><span><span class="rule-name">${escHtml(item.ruleName||item.description)}</span><span class="rule-id">${escHtml(item.ruleId||'')}</span>${item.legacyRuleIds?.length?`<span class="rule-legacy-id">Legacy: ${escHtml(item.legacyRuleIds.join(', '))}</span>`:''}</span><span class="tag">${escHtml(item.severity || 'review')}</span>${languageBadge(item.language, item.languageConfidence)}</div>
          <div class="rule-detail-guidance">${escHtml(item.description)}</div>
          <div>${findingLocationLink(item, 'review')}</div>
          <div class="rule-full-context">${renderRuleContext(item)}</div>${languageIntervalsDetails(item)}
          <div class="forbidden-rule">${escHtml(item.pattern)}</div>
        </article>`);
      return section('Words and expressions to review', matches.length,
        `<div class="rule-detail-container">${ruleSummary}${buildRuleDetailFilters(matches)}${details}</div>`, false);
    }

    function languageIntervalsDetails(item){const ranges=item.languageRanges||[];if(!ranges.length)return'';const text=item.fullContext||item.context||'';return `<details class="language-intervals"><summary>Language intervals and inheritance sources (${ranges.length})</summary>${ranges.map(r=>`<div class="language-interval">${languageBadge(r.language,0)} <span>${r.start}–${r.end}</span> <span class="language-source">${escHtml(r.source||'unknown source')}${r.rawLanguage?` · ${escHtml(r.rawLanguage)}`:''}</span><span class="language-interval-text">${escHtml(r.text??text.slice(r.start,r.end))}</span></div>`).join('')}</details>`;}

    function languageName(language) { return ({sv:'Swedish',en:'English',mixed:'Mixed',other:'Other',unknown:'Unknown'})[language] || language; }
    function languageBadge(language, confidence = 0) { const value=language||'unknown'; return `<span class="language-badge ${escHtml(value)}">${escHtml(value.toUpperCase())}${confidence?` · ${Math.round(confidence*100)}%`:''}</span>`; }

    function renderResults(filename, entries, citations, report, issues, forbiddenMatches, potentialInvalidCitations, officialWritingIssues, total, start, isSwedish, languageProfile = {}) {
      const zoteroCitationCount = citations.filter(citation => citation.citationSource === 'zotero').length;
      const plainCitationCount = citations.filter(citation => citation.citationSource === 'plain').length;
      const distribution=languageProfile.distribution||{};
      const totalLanguageLetters=Math.max(1,(distribution.sv||0)+(distribution.en||0)+(distribution.other||0)+(distribution.unknown||0)+(distribution.mixed||0));
      const languageSummary=['sv','en','other','mixed','unknown'].filter(key=>distribution[key]).map(key=>languageBadge(key,(distribution[key]||0)/totalLanguageLetters)).join(' ');
      docInfo.innerHTML = `<strong>${escHtml(filename)}</strong> ${total} paragraphs · ${entries.length} reference list entries · ${citations.length} citation occurrences (${zoteroCitationCount} Zotero fields, ${plainCitationCount} plain text) · ${start >= 0 ? `Reference list found at paragraph ${start + 1}.` : 'No reference list section detected.'}<div class="language-summary"><strong>Primary language: ${escHtml(languageName(languageProfile.language||'unknown'))} · ${Math.round((languageProfile.confidence||0)*100)}% of analysed text</strong><span class="language-badge unknown">Known-language coverage: ${Math.round((languageProfile.knownCoverage||0)*100)}%</span>${languageSummary}<span class="language-badge mixed">Mixed paragraphs: ${languageProfile.mixedParagraphs||0}</span></div>`;
      docInfo.classList.add('show');
      const cited = entries.filter(entry => entry.cites.length).length;
      setSummary('total', entries.length, entries.length ? 'ok' : 'warn');
      setSummary('cited', cited, cited === entries.length && entries.length ? 'ok' : cited ? '' : 'warn');
      setSummary('orphan', report.orphanCites.length, report.orphanCites.length ? 'warn' : 'ok');
      setSummary('issues', issues.length, issues.length ? 'warn' : 'ok');
      summaryCards.classList.add('show');
      resultActions.classList.add('show');
      results.innerHTML = buildRefListSection(entries) + buildCitationOccurrencesSection(citations) + buildOrphanSection(report.orphanCites) + buildPotentialInvalidCitationsSection(potentialInvalidCitations) + buildUncitedSection(report.uncitedRefs) + buildFormatSection(issues, entries) + buildRuleFindingSummary(officialWritingIssues, potentialInvalidCitations, forbiddenMatches) + buildOfficialSkbWritingSection(officialWritingIssues) + buildForbiddenWordsSection(forbiddenMatches);
      resetBtn.classList.add('show');
    }

    function buildRefListSection(entries) {
      const rows = entries.length
        ? entries.map((entry, index) => {
            const sections = [...new Set(entry.cites.map(citation => citation.section).filter(Boolean))]
              .slice(0, 5).map(escHtml).join('<br>');
            const sourceBadges = [...new Map(entry.cites.map(citation => [citation.citationSource, citation])).values()]
              .map(citationSourceBadge).join(' ');
            return `
              <tr class="${entry.cites.length ? '' : 'warn-row'}">
                <td><span class="ref-key">${escHtml(entry.key)}</span></td>
                <td class="ref-text">${renderTextWithBold(entry.body, entry.boldSpans)}</td>
                <td class="cite-count">${entry.cites.length}</td>
                <td class="cite-pages">${sections}${sourceBadges ? `<div style="margin-top:5px">${sourceBadges}</div>` : ''}</td>
                <td class="zotero-cell">
                  <button class="zotero-row-btn" type="button" data-kind="reference" data-index="${index}" data-search-id="reference-${index}" data-result-id="zotero-reference-${index}" title="Search Zotero using authors, publication year, and title extracted from this reference">Check Zotero</button>
                  <div id="zotero-reference-${index}" class="zotero-inline-results"></div>
                </td>
              </tr>`;
          }).join('')
        : '<tr><td colspan="5" class="empty-notice">No reference list detected.</td></tr>';
      return section(
        'Reference list entries',
        entries.length,
        `<table class="ref-table ref-list-table"><colgroup><col class="col-key"><col class="col-text"><col class="col-cited"><col class="col-sections"><col class="col-zotero"></colgroup><thead><tr><th>Key</th><th>Reference text</th><th>Cited (#)</th><th>In section(s)</th><th>Zotero</th></tr></thead><tbody>${rows}</tbody></table>`,
        true
      );
    }

    function findCitationDisplaySpan(citation) {
      const text = String(citation?.paraText || '');
      if (!text) return null;
      if (Number.isFinite(citation?.matchStart) && Number.isFinite(citation?.matchEnd) && citation.matchStart >= 0 && citation.matchEnd > citation.matchStart && citation.matchEnd <= text.length) return {start:citation.matchStart,end:citation.matchEnd};
      const candidates=[];
      if(citation?.author&&citation?.year)candidates.push(`${citation.author} (${citation.year})`,`${citation.author} ${citation.year}`);
      candidates.push(citation?.key,citation?.raw);
      for(const value of candidates){const candidate=String(value||'').trim();if(!candidate)continue;const offset=text.indexOf(candidate);if(offset>=0)return{start:offset,end:offset+candidate.length};}
      const year=String(citation?.year||citation?.key?.match(/\b(?:1[89]\d{2}|20\d{2})[a-z]?\b/i)?.[0]||'');
      const author=String(citation?.author||citation?.key||'').replace(/\s+(?:1[89]\d{2}|20\d{2})[a-z]?.*$/i,'').trim();
      if(author&&year){const pattern=escapeRegExp(author).replace(/\\\s+/g,'\\\\s+');const match=new RegExp(`${pattern}[\\s,;()]*${escapeRegExp(year)}`,'i').exec(text);if(match)return{start:match.index,end:match.index+match[0].length};}
      return null;
    }

    function renderCitationContext(citation,radius=90){
      const text=String(citation?.paraText||'');if(!text)return'';
      const span=findCitationDisplaySpan(citation);
      if(!span){const shortened=text.length>radius*2?`${text.slice(0,radius*2)}…`:text;return escHtml(shortened);}
      const start=Math.max(0,span.start-radius),end=Math.min(text.length,span.end+radius);
      return `${start>0?'…':''}${escHtml(text.slice(start,span.start))}<strong class="citation-context-match">${escHtml(text.slice(span.start,span.end))}</strong>${escHtml(text.slice(span.end,end))}${end<text.length?'…':''}`;
    }

    function citationLocation(citation){
      const paragraphNumber=citation.paragraphNumber||((citation.paraIndex??0)+1);
      let section=citation.regionLabel||citation.section||'Main text';
      if(citation.documentRegion==='after-references'&&(!section||REF_HEADING_RE.test(normaliseHeadingText(section))))section='After references';
      if(citation.documentRegion==='references')section='References';
      return{section,paragraphNumber};
    }
    function renderCitationLocation(citation){const location=citationLocation(citation);return `<span class="citation-location-region">${escHtml(location.section)}</span><span class="citation-location-paragraph">${currentFormat === 'pdf' ? 'PDF' : 'DOCX'} paragraph ${location.paragraphNumber}</span>`;}

    function runCitationDisplayRegressionTests(){
      const failures=[];
      const after=citationLocation({documentRegion:'after-references',regionLabel:'References',paragraphNumber:240});if(after.section!=='After references'||after.paragraphNumber!==240)failures.push('Post-reference location failed');
      const appendix=citationLocation({documentRegion:'after-references',regionLabel:'Appendix A',paragraphNumber:241});if(appendix.section!=='Appendix A')failures.push('Post-reference heading failed');
      const citation={paraText:'Long introductory wording before Vieira and Rosa (1996) and more text afterwards.',author:'Vieira and Rosa',year:'1996',key:'Vieira and Rosa 1996'};
      const context=renderCitationContext(citation,12);if(!context.startsWith('…')||!context.includes('<strong class="citation-context-match">Vieira and Rosa (1996)</strong>'))failures.push('Citation-centred highlight failed');
      if(failures.length)console.error('Citation display regression tests failed:',failures);else console.info('Citation display regression tests passed.');return failures;
    }

    function buildCitationOccurrencesSection(items) {
      const zoteroCount = items.filter(item => item.citationSource === 'zotero').length;
      const plainCount = items.filter(item => item.citationSource === 'plain').length;
      const fieldCount = items.filter(item => item.citationSource === 'field').length;
      const summary = `<div class="tag-list" style="margin-bottom:12px">
        <span class="citation-source-badge zotero">Z Zotero field: ${zoteroCount}</span>
        <span class="citation-source-badge plain">T Plain text: ${plainCount}</span>
        ${fieldCount ? `<span class="citation-source-badge field">F Other Word field: ${fieldCount}</span>` : ''}
      </div>`;
      const rows = items.length ? items.map(citation => `
        <tr>
          <td><span class="ref-key">${escHtml(citation.key)}</span></td>
          <td>${citationSourceBadge(citation)}<div class="citation-source-detail">${escHtml(citation.citationSourceDetail || '')}</div></td>
          <td>${renderCitationLocation(citation)}</td>
          <td><div class="citation-context">${renderCitationContext(citation)}</div></td>
        </tr>`).join('') : '<tr><td colspan="4" class="empty-notice">No citation occurrences detected.</td></tr>';
      return section(currentFormat === 'pdf' ? 'Citation occurrences and page source' : 'Citation occurrences and Word source', items.length,
        `${summary}<table class="ref-table"><thead><tr><th>Citation key</th><th>Source</th><th>Location</th><th>Context</th></tr></thead><tbody>${rows}</tbody></table>`, false);
    }

    function buildOrphanSection(items) {
      const body = items.length
        ? `<table class="ref-table orphan-table"><thead><tr><th>Citation</th><th>Closest entry</th><th>Context</th><th>Section</th><th>Zotero</th></tr></thead><tbody>${items.map((citation, index) => `
            <tr class="error-row">
              <td>
                <span class="ref-key">${escHtml(citation.key)}</span>
                <div class="citation-meta">${citationSourceBadge(citation)}<span class="citation-type">${escHtml(citation.type)}</span></div>
              </td>
              <td>${citation.suggestion
                ? `<span class="ref-key">${escHtml(citation.suggestion.key)}</span><div class="suggestion-score" title="${escHtml(citation.suggestion.body)}">${Math.round((citation.suggestionScore || 0) * 100)}% match</div>`
                : '<span class="rule-legacy-id">no similar entry</span>'}</td>
              <td><div class="citation-context">${renderCitationContext(citation)}</div></td>
              <td>${renderCitationLocation(citation)}</td>
              <td class="zotero-cell">
                <button class="zotero-row-btn" type="button" data-kind="citation" data-index="${index}" data-search-id="citation-${index}" data-result-id="zotero-citation-${index}" title="Search Zotero using this citation key">Check Zotero</button>
                <div id="zotero-citation-${index}" class="zotero-inline-results"></div>
              </td>
            </tr>`).join('')}</tbody></table>`
        : '<p class="empty-notice">All in-text citations match a reference list entry.</p>';
      return section('In-text citations with no matching reference list entry', items.length, body, items.length > 0);
    }

    function buildUncitedSection(items){const body=items.length?`<div class="tag-list">${items.map(e=>`<div class="tag warn-tag">⚠ <code>${escHtml(e.key)}</code>${e.suggestedFor?.length?` <span class="rule-legacy-id">cited as ${escHtml(e.suggestedFor.join(', '))}?</span>`:''}</div>`).join('')}</div>`:'<p class="empty-notice">Every reference in the list is cited at least once.</p>';return section('Reference list entries never cited in text',items.length,body);}
    function buildFormatSection(issues,entries){const map=new Map(entries.map(e=>[e.key,e.body]));const groups=new Map();issues.forEach(i=>(groups.get(i.key)||groups.set(i.key,[]).get(i.key)).push(i));const body=issues.length?`<table class="ref-table"><thead><tr><th>Key</th><th>Reference text</th><th>Issues</th></tr></thead><tbody>${[...groups].map(([key,list])=>`<tr><td><span class="ref-key">${escHtml(key)}</span></td><td>${truncate(escHtml(map.get(key)||''),100)}</td><td><ul class="issue-list">${list.map(i=>`<li>[${i.severity.toUpperCase()}] ${escHtml(i.issue)}</li>`).join('')}</ul></td></tr>`).join('')}</tbody></table>`:'<p class="empty-notice">No SKB format rule violations detected.</p>';return section('SKB format rule issues',issues.length,body);}
    /*
      Reference-list regression tests. Every reference below is copied from
      1215757 — the correct ones from its example sections, the incorrect ones
      from the "Fel" column of appendix 2 and from the rules in chapter 4. A
      rule that fires on the guide's own correct example is a false positive,
      which is the failure mode these tests exist to catch.
    */
    /*
      Designation references, sections 4.10-4.12 of 1215757. The year is part
      of the designation, so "SSMFS 2008:21" and "SSMFS 2008:37" are different
      documents. Read as author-year citations both collapse to "SSMFS 2008",
      which used to report a citation of one regulation as a correct match for
      the other, and two such references in one list as duplicates.
    */
    /*
      Abbreviated reference names, chapter 4.9 of 1215757, against author-year
      references. Both are written "<name>, <year>." so nothing but the shape
      of the name separates them, and getting it wrong is not a cosmetic
      mistake: an author-year reference read as an abbreviated name is entered
      under its whole author list with no year, so two works by the same
      authors collide and are reported as duplicates of each other.

      The abbreviated names below are the ones 1215757 lists; the author lists
      are taken from the reference list of SKB TR-23-02.
    */
