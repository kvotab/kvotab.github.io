/* ==========================================================================
   SKB REFERENCE CHECKER — docx

   Reading a .docx: run properties, the style chain for language and bold,
   and the paragraph model everything downstream consumes.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function normaliseWordLanguage(value) {
      const language = String(value || '').trim().toLowerCase().replace('_','-');
      if (/^sv(?:-|$)/.test(language)) return 'sv';
      if (/^en(?:-|$)/.test(language)) return 'en';
      return language ? 'other' : 'unknown';
    }

    function countLetters(value) {
      return (String(value || '').match(/\p{L}/gu) || []).length;
    }

    function inferLanguageFromText(value) {
      const words = String(value || '').toLowerCase().match(/\p{L}+/gu) || [];
      if (words.length < 3) return { language: 'unknown', confidence: 0, evidence: { sv:0, en:0 } };
      const svWords = new Set(['och','att','som','inte','är','för','med','av','till','den','det','en','ett','kan','ska','har','från','vid','eller','samt']);
      const enWords = new Set(['and','that','which','not','is','are','for','with','of','to','the','a','an','can','shall','has','from','at','or']);
      let sv=0,en=0; for(const word of words){if(svWords.has(word))sv++;if(enWords.has(word))en++;}
      const total=sv+en; if(total<2 || sv===en)return{language:'unknown',confidence:0,evidence:{sv,en}};
      const language=sv>en?'sv':'en'; return{language,confidence:Math.min(.75,Math.max(.5,Math.abs(sv-en)/total)),evidence:{sv,en}};
    }

    function getDirectWordLanguage(node,NS){if(!node)return{language:'unknown',raw:'',source:'none'};const lang=[...node.childNodes].find(c=>c.nodeType===1&&c.namespaceURI===NS&&c.localName==='lang')||node.getElementsByTagNameNS(NS,'lang')[0];const raw=lang?.getAttribute('w:val')||lang?.getAttributeNS(NS,'val')||'';return{language:normaliseWordLanguage(raw),raw,source:'direct'};}
    /*
      Whether a set of run properties turns bold on, off, or says nothing at
      all. "Not specified" has to stay distinct from "off", because Word
      resolves bold down a chain of styles and only an explicit value ends the
      search — a style that switches bold on would otherwise be cancelled by
      every ancestor that never mentioned it.
    */
    function readBoldFlag(rPr,NS){
      if(!rPr)return null;
      const node=rPr.getElementsByTagNameNS(NS,'b')[0];
      if(!node)return null;
      const value=node.getAttribute('w:val')??node.getAttributeNS(NS,'val');
      return value===null?true:!['0','false','none','off'].includes(String(value).toLowerCase());
    }

    function parseWordStyles(xml,NS){const empty={styles:new Map(),defaultStyles:{paragraph:'',character:''},docDefault:{language:'unknown',raw:'',source:'none'}};if(!xml)return empty;const doc=new DOMParser().parseFromString(xml,'application/xml'),styles=new Map();for(const node of [...doc.getElementsByTagNameNS(NS,'style')]){const id=node.getAttribute('w:styleId')||node.getAttributeNS(NS,'styleId')||'';if(!id)continue;const based=node.getElementsByTagNameNS(NS,'basedOn')[0],basedOn=based?.getAttribute('w:val')||based?.getAttributeNS(NS,'val')||'',type=node.getAttribute('w:type')||node.getAttributeNS(NS,'type')||'',isDefault=['1','true'].includes((node.getAttribute('w:default')||node.getAttributeNS(NS,'default')||'').toLowerCase()),nameNode=node.getElementsByTagNameNS(NS,'name')[0],name=nameNode?.getAttribute('w:val')||nameNode?.getAttributeNS(NS,'val')||id,rPr=[...node.childNodes].find(c=>c.nodeType===1&&c.namespaceURI===NS&&c.localName==='rPr'),direct=getDirectWordLanguage(rPr,NS);styles.set(id,{id,basedOn,type,isDefault,name,language:direct.language,rawLanguage:direct.raw,bold:readBoldFlag(rPr,NS)});}const defaultStyles={paragraph:'',character:''};for(const style of styles.values())if(style.isDefault&&Object.hasOwn(defaultStyles,style.type))defaultStyles[style.type]=style.id;const rp=doc.getElementsByTagNameNS(NS,'docDefaults')[0]?.getElementsByTagNameNS(NS,'rPrDefault')[0]?.getElementsByTagNameNS(NS,'rPr')[0],direct=getDirectWordLanguage(rp,NS);return{styles,defaultStyles,docDefaultBold:readBoldFlag(rp,NS),docDefault:{language:direct.language,raw:direct.raw,source:'document default'}};}
    function resolveStyleLanguage(id,model,visited=new Set()){if(!id||visited.has(id))return null;visited.add(id);const style=model.styles.get(id);if(!style)return null;if(style.language!=='unknown')return{language:style.language,raw:style.rawLanguage,source:`${style.type||'style'} style: ${style.name} (${style.id})`};return resolveStyleLanguage(style.basedOn,model,visited);}
    function resolveStyleBold(id,model,visited=new Set()){
      if(!id||visited.has(id))return null;
      visited.add(id);
      const style=model.styles.get(id);
      if(!style)return null;
      if(typeof style.bold==='boolean')return style.bold;
      return resolveStyleBold(style.basedOn,model,visited);
    }

    /* Run formatting wins over the character style, which wins over the
       paragraph's own formatting, then its style, then the document default —
       the order resolveRunLanguage already establishes for language. */
    function resolveRunBold(run,paragraph,model,NS){
      const rPr=run.getElementsByTagNameNS(NS,'rPr')[0],direct=readBoldFlag(rPr,NS);
      if(direct!==null)return direct;
      const character=resolveStyleBold(getStyleId(rPr,'rStyle',NS)||model.defaultStyles.character,model);
      if(character!==null)return character;
      const pPr=paragraph.getElementsByTagNameNS(NS,'pPr')[0];
      const paragraphDirect=readBoldFlag(pPr?.getElementsByTagNameNS(NS,'rPr')[0],NS);
      if(paragraphDirect!==null)return paragraphDirect;
      const paragraphStyle=resolveStyleBold(getStyleId(pPr,'pStyle',NS)||model.defaultStyles.paragraph,model);
      if(paragraphStyle!==null)return paragraphStyle;
      return model.docDefaultBold===true;
    }

    function getStyleId(props,name,NS){const node=props?.getElementsByTagNameNS(NS,name)[0];return node?.getAttribute('w:val')||node?.getAttributeNS(NS,'val')||'';}
    function resolveRunLanguage(run,paragraph,model,NS){const rp=run.getElementsByTagNameNS(NS,'rPr')[0],direct=getDirectWordLanguage(rp,NS);if(direct.language!=='unknown')return{...direct,source:'run direct formatting'};const char=resolveStyleLanguage(getStyleId(rp,'rStyle',NS)||model.defaultStyles.character,model);if(char)return char;const pp=paragraph.getElementsByTagNameNS(NS,'pPr')[0],pd=getDirectWordLanguage(pp,NS);if(pd.language!=='unknown')return{...pd,source:'paragraph direct formatting'};const ps=resolveStyleLanguage(getStyleId(pp,'pStyle',NS)||model.defaultStyles.paragraph,model);if(ps)return ps;if(model.docDefault.language!=='unknown')return model.docDefault;return{language:'unknown',raw:'',source:'no language metadata'};}
    function extractRunVisibleText(run,NS){let value='';(function walk(node){for(let c=node.firstChild;c;c=c.nextSibling){if(c.nodeType!==1)continue;if(c.namespaceURI!==NS){walk(c);continue;}if(c.localName==='t')value+=c.textContent||'';else if(c.localName==='tab')value+='\\t';else if(c.localName==='br'||c.localName==='cr')value+=' ';else if(c.localName!=='instrText')walk(c);}})(run);return value;}
    function extractParagraphLanguageEvidence(node,NS,model){const counts={sv:0,en:0,other:0,unknown:0},ranges=[];let offset=0;for(const run of [...node.getElementsByTagNameNS(NS,'r')]){const text=extractRunVisibleText(run,NS);if(!text)continue;const resolved=resolveRunLanguage(run,node,model,NS),letters=countLetters(text);counts[resolved.language]=(counts[resolved.language]||0)+letters;const prev=ranges.at(-1);if(prev&&prev.end===offset&&prev.language===resolved.language&&prev.source===resolved.source){prev.end+=text.length;prev.letters+=letters;prev.text+=text;}else ranges.push({start:offset,end:offset+text.length,language:resolved.language,rawLanguage:resolved.raw,source:resolved.source,letters,text});offset+=text.length;}return{counts,ranges};}

    function classifyParagraphLanguage(text, metadata) {
      const counts={sv:0,en:0,other:0,unknown:0,...metadata.counts};
      const totalLetters=Math.max(1,countLetters(text));
      const markedTotal=counts.sv+counts.en+counts.other;
      const metadataCoverage=Math.min(1,markedTotal/totalLetters);
      const inferred=inferLanguageFromText(text);
      if(markedTotal>0&&metadataCoverage>=.5){
        const ranked=[['sv',counts.sv],['en',counts.en],['other',counts.other]].sort((a,b)=>b[1]-a[1]);
        const dominance=ranked[0][1]/markedTotal;
        if(dominance>=.7)return{language:ranked[0][0],confidence:dominance*metadataCoverage,evidence:counts,source:'word-language',metadataCoverage};
        return{language:'mixed',confidence:Math.max(.5,1-dominance),evidence:counts,source:'word-language',metadataCoverage};
      }
      if(inferred.language!=='unknown')return{language:inferred.language,confidence:Math.min(.75,Math.max(inferred.confidence,metadataCoverage*.6)),evidence:{...counts,inferredSv:inferred.evidence.sv,inferredEn:inferred.evidence.en},source:markedTotal?'word-language+text-fallback':'text-fallback',metadataCoverage};
      if(markedTotal>0){const ranked=[['sv',counts.sv],['en',counts.en],['other',counts.other]].sort((a,b)=>b[1]-a[1]),dominance=ranked[0][1]/markedTotal;return{language:dominance>=.7?ranked[0][0]:'mixed',confidence:dominance*metadataCoverage,evidence:counts,source:'sparse-word-language',metadataCoverage};}
      return{language:'unknown',confidence:0,evidence:counts,source:'unknown',metadataCoverage:0};
    }

    function calculateDocumentLanguage(paragraphs) {
      const distribution={sv:0,en:0,other:0,unknown:0,mixed:0};let mixedParagraphs=0;
      for(const paragraph of paragraphs){const letters=countLetters(paragraph.text),evidence=paragraph.languageEvidence||{},marked=(evidence.sv||0)+(evidence.en||0)+(evidence.other||0);if(paragraph.language==='mixed'){mixedParagraphs++;if(marked){distribution.sv+=evidence.sv||0;distribution.en+=evidence.en||0;distribution.other+=evidence.other||0;distribution.unknown+=Math.max(0,letters-marked);}else distribution.mixed+=letters;}else if(['sv','en','other'].includes(paragraph.language))distribution[paragraph.language]+=letters;else distribution.unknown+=letters;}
      const total=Object.values(distribution).reduce((a,b)=>a+b,0),known=distribution.sv+distribution.en+distribution.other,ranked=[['sv',distribution.sv],['en',distribution.en],['other',distribution.other]].sort((a,b)=>b[1]-a[1]),dominantShare=total?ranked[0][1]/total:0,knownCoverage=total?known/total:0;
      return{language:dominantShare>=.7&&knownCoverage>=.7?ranked[0][0]:knownCoverage>=.5?'mixed':'unknown',confidence:dominantShare,knownCoverage,distribution,mixedParagraphs,totalLetters:total};
    }

    function languageAtRange(paragraph,start,end) {
      const overlaps=(paragraph.languageRanges||[]).filter(range=>range.start<end&&start<range.end&&['sv','en'].includes(range.language));
      if(!overlaps.length)return{language:paragraph.language,confidence:paragraph.languageConfidence||0};
      const counts={sv:0,en:0};for(const range of overlaps)counts[range.language]+=Math.max(0,Math.min(end,range.end)-Math.max(start,range.start));
      const total=counts.sv+counts.en;if(!total)return{language:paragraph.language,confidence:paragraph.languageConfidence||0};
      const language=counts.sv===counts.en?'mixed':counts.sv>counts.en?'sv':'en';return{language,confidence:Math.max(counts.sv,counts.en)/total};
    }

    function parseDocXml(xml, stylesXml = '') {
      const doc = new DOMParser().parseFromString(xml, 'application/xml');
      const NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
      const styleModel = parseWordStyles(stylesXml, NS);
      const paragraphs = [...doc.getElementsByTagNameNS(NS, 'p')].map((node, index) => {
        const pPr = node.getElementsByTagNameNS(NS, 'pPr')[0];
        const styleNode = pPr?.getElementsByTagNameNS(NS, 'pStyle')[0];
        const numPr = pPr?.getElementsByTagNameNS(NS, 'numPr')[0];
        let ancestor = node.parentNode;
        let isInTable = false;
        let tableDepth = 0;
        while (ancestor && ancestor !== doc) {
          if (ancestor.nodeType === 1 && ancestor.namespaceURI === NS && ancestor.localName === 'tbl') {
            isInTable = true;
            tableDepth++;
          }
          ancestor = ancestor.parentNode;
        }
        const extracted = extractTextFromParagraph(node, NS, styleModel);
        const rawText = extracted.text;
        const leadingTrim = rawText.length - rawText.trimStart().length;
        const trimmedText = rawText.trim();
        const languageMetadata=extractParagraphLanguageEvidence(node,NS,styleModel);
        languageMetadata.ranges = languageMetadata.ranges.map(range => ({
          ...range,
          start: Math.max(0, range.start - leadingTrim),
          end: Math.max(0, Math.min(trimmedText.length, range.end - leadingTrim))
        })).filter(range => range.end > range.start);
        const language=classifyParagraphLanguage(trimmedText,languageMetadata);
        const formatSpans = (extracted.formatSpans || []).map(span => ({
          ...span,
          start: Math.max(0, span.start - leadingTrim),
          end: Math.max(0, Math.min(trimmedText.length, span.end - leadingTrim))
        })).filter(span => span.end > span.start);
        return {
          text: trimmedText, fields: extracted.fields, formatSpans,
          hasZoteroBibliography: extracted.fields.some(field => field.isZoteroBibliography),
          style: (styleNode?.getAttribute('w:val') || '').toLowerCase(),
          isInTable,
          tableDepth,
          numId: numPr?.getElementsByTagNameNS(NS, 'numId')[0]?.getAttribute('w:val') || '', index,
          language:language.language, languageConfidence:language.confidence, languageSource:language.source,
          languageEvidence:language.evidence, languageRanges:languageMetadata.ranges
        };
      });
      let section = '';
      for (const paragraph of paragraphs) { if (headingLevel(paragraph.style) && paragraph.text) section = paragraph.text; paragraph.section = section; }
      const languageProfile=calculateDocumentLanguage(paragraphs);
      return { paragraphs, isSwedish: languageProfile.language==='sv', languageProfile };
    }

    /*
      Character formatting that the writing guides care about. Superscript,
      subscript, italic and underline carry meaning in chapters 4 and 5 of
      1469987 and cannot be seen in the plain text alone.
    */
    function readRunFormatting(run, NS, styleModel = null, paragraph = null) {
      /* Bold comes from the style chain as well as from the run, so it is
         resolved before the early return: a run with no formatting of its own
         can still be bold through its style. */
      const bold = styleModel && paragraph ? resolveRunBold(run, paragraph, styleModel, NS) : false;
      const rPr = run.getElementsByTagNameNS(NS, 'rPr')[0];
      if (!rPr) return { sup: false, sub: false, italic: false, underline: false, bold };
      const own = child => {
        const node = rPr.getElementsByTagNameNS(NS, child)[0];
        if (!node) return null;
        const value = node.getAttribute('w:val') ?? node.getAttributeNS(NS, 'val');
        return value === null ? 'on' : String(value).toLowerCase();
      };
      const vertAlign = own('vertAlign');
      const isOn = value => value !== null && !['0', 'false', 'none', 'off'].includes(value);
      return {
        sup: vertAlign === 'superscript',
        sub: vertAlign === 'subscript',
        italic: isOn(own('i')),
        underline: isOn(own('u')),
        bold
      };
    }

    function extractTextFromParagraph(node, NS, styleModel = null) {
      let text = '';
      const stack = [];
      const extractedFields = [];
      const formatSpans = [];
      let hyperlinkDepth = 0;
      (function walk(parent) {
        for (let child = parent.firstChild; child; child = child.nextSibling) {
          if (child.nodeType !== 1) continue;
          if (child.namespaceURI !== NS) { walk(child); continue; }
          if (child.localName === 'hyperlink') {
            hyperlinkDepth++; walk(child); hyperlinkDepth--; continue;
          }
          if (child.localName === 'r') {
            const start = text.length;
            const formatting = readRunFormatting(child, NS, styleModel, node);
            walk(child);
            if (text.length > start) {
              formatSpans.push({ start, end: text.length, inHyperlink: hyperlinkDepth > 0, ...formatting });
            }
            continue;
          }
          if (child.localName === 'fldChar') {
            const type = child.getAttribute('w:fldCharType');
            if (type === 'begin') {
              stack.push({ instruction: '', result: '', inResult: false, start: null, end: null });
            } else if (type === 'separate' && stack.length) {
              const field = stack.at(-1);
              field.inResult = true;
              field.start = text.length;
            } else if (type === 'end' && stack.length) {
              const field = stack.pop();
              field.end = text.length;
              const instruction = field.instruction.replace(/\s+/g, ' ').trim();
              const isZoteroCitation = /^ADDIN\s+ZOTERO_ITEM\s+CSL_CITATION\b/i.test(instruction);
              const isZoteroBibliography = /^ADDIN\s+ZOTERO_BIBL\b/i.test(instruction);
              extractedFields.push({
                type: instruction.match(/^([A-Z]+)/i)?.[1]?.toUpperCase() || 'FIELD',
                instruction, result: field.result,
                start: field.start ?? field.end ?? text.length,
                end: field.end ?? text.length,
                isZoteroCitation, isZoteroBibliography
              });
            }
          } else if (child.localName === 'instrText' && stack.length) {
            stack.at(-1).instruction += child.textContent || '';
          } else if (child.localName === 'tab') {
            text += '\t';
          } else if (child.localName === 'br' || child.localName === 'cr') {
            text += ' ';
          } else if (child.localName === 't') {
            const value = child.textContent || '';
            text += value;
            for (const field of stack) if (field.inResult) field.result += value;
          } else walk(child);
        }
      })(node);
      return { text, fields: extractedFields, formatSpans };
    }
