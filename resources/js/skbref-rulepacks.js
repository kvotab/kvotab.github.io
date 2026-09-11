/* ==========================================================================
   SKB REFERENCE CHECKER — rulepacks

   Loading, storing and exporting the project terminology rule packs.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    const RULE_PACK_STORAGE_KEY = 'skbref-rule-packs';
    const BUILT_IN_PACK_NAME = 'Project terminology (built in)';

    let loadedRulePacks = [];

    function readStoredRulePacks() {
      try {
        const raw = localStorage.getItem(RULE_PACK_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
      } catch (error) {
        console.warn('Could not read stored rule packs:', error);
        return [];
      }
    }

    function storeRulePacks() {
      try {
        localStorage.setItem(RULE_PACK_STORAGE_KEY, JSON.stringify(loadedRulePacks.map(pack => ({
          name: pack.name, description: pack.description, enabled: pack.enabled, rules: pack.rules
        }))));
      } catch (error) {
        console.warn('Could not store rule packs:', error);
      }
    }

    function normaliseRulePack(raw, fallbackName) {
      const body = Array.isArray(raw) ? { rules: raw } : (raw && typeof raw === 'object' ? raw : null);
      if (!body || !Array.isArray(body.rules)) {
        throw new Error('A rule pack must be an array of rules, or an object with a "rules" array.');
      }
      const rules = body.rules
        .filter(rule => rule && typeof rule.pattern === 'string' && rule.pattern.trim())
        .map(rule => ({ enabled: rule.enabled !== false, ...rule }));
      if (!rules.length) throw new Error('The rule pack contains no usable rules.');
      for (const rule of rules) {
        try {
          new RegExp(rule.pattern, rule.flags || 'gu');
        } catch (error) {
          throw new Error(`Rule "${rule.pattern}" is not a valid regular expression: ${error.message}`);
        }
      }
      const name = String(body.name || fallbackName || 'Rule pack').trim();
      const pack = { name, description: String(body.description || ''), enabled: body.enabled !== false, rules };
      ensureRuleMetadata(pack.rules, 'review', { category: 'terminology', severity: 'review', flags: 'gu' });
      for (const rule of pack.rules) rule.packName = name;
      return pack;
    }

    /* Built-in rules first, then every enabled pack in load order. */
    function activeReviewRules() {
      const rules = FORBIDDEN_WORD_RULES.map(rule => ({ ...rule, packName: rule.packName || BUILT_IN_PACK_NAME }));
      for (const pack of loadedRulePacks) {
        if (pack.enabled === false) continue;
        rules.push(...pack.rules);
      }
      return rules;
    }

    function activeRulePackNames() {
      return [BUILT_IN_PACK_NAME, ...loadedRulePacks.filter(pack => pack.enabled !== false).map(pack => pack.name)];
    }

    function renderRulePackList() {
      const list = document.getElementById('rule-pack-list');
      if (!list) return;
      const builtIn = `<li class="rule-pack-row built-in">
          <label><input type="checkbox" checked disabled> ${escHtml(BUILT_IN_PACK_NAME)}</label>
          <span class="rule-pack-count">${FORBIDDEN_WORD_RULES.filter(rule => rule.enabled !== false).length} rules</span>
          <span></span>
          <p class="rule-pack-note">Always applied, together with the three official SKB guides.</p>
        </li>`;
      const packs = loadedRulePacks.map((pack, index) => `<li class="rule-pack-row">
          <label><input type="checkbox" data-pack-index="${index}"${pack.enabled === false ? '' : ' checked'}> ${escHtml(pack.name)}</label>
          <span class="rule-pack-count">${pack.rules.filter(rule => rule.enabled !== false).length} rules</span>
          <button type="button" class="rule-pack-remove" data-remove-pack="${index}" title="Remove this rule pack">Remove</button>
          ${pack.description ? `<p class="rule-pack-note">${escHtml(pack.description)}</p>` : ''}
        </li>`).join('');
      list.innerHTML = builtIn + packs;
      const summary = document.getElementById('rule-pack-summary');
      if (summary) summary.textContent = `Rule packs (${activeRulePackNames().length} active)`;
    }

    async function addRulePackFiles(files) {
      if (!files.length) return;
      const status = document.getElementById('rule-pack-status');
      const added = [], failed = [];
      for (const file of files) {
        try {
          const pack = normaliseRulePack(JSON.parse(await file.text()), file.name.replace(/\.json$/i, ''));
          const existing = loadedRulePacks.findIndex(item => item.name === pack.name);
          if (existing >= 0) loadedRulePacks[existing] = pack; else loadedRulePacks.push(pack);
          added.push(`${pack.name} (${pack.rules.length} rule${pack.rules.length === 1 ? '' : 's'})`);
        } catch (error) {
          failed.push(`${file.name}: ${error.message}`);
        }
      }
      storeRulePacks();
      renderRulePackList();
      if (status) {
        status.textContent = [added.length ? `Loaded ${added.join(', ')}.` : '', failed.join(' ')].filter(Boolean).join(' ');
        status.className = failed.length ? 'error' : '';
      }
      if (added.length) await reanalyseCurrentDocument();
    }

    function exportRulePacks() {
      const payload = {
        name: 'skbref active rules',
        description: 'Built-in project terminology plus every loaded rule pack, exported from the SKB Reference Checker.',
        exported: new Date().toISOString().slice(0, 10),
        rules: activeReviewRules().map(rule => ({
          pattern: rule.pattern,
          description: rule.description || '',
          enabled: rule.enabled !== false,
          ...(rule.flags && rule.flags !== 'gu' ? { flags: rule.flags } : {}),
          ...(rule.language ? { language: rule.language } : {}),
          ...(rule.severity && rule.severity !== 'review' ? { severity: rule.severity } : {}),
          ...(rule.custom ? { custom: rule.custom } : {}),
          ...(rule.packName ? { pack: rule.packName } : {})
        }))
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'skbref-rules.json';
      link.click();
      URL.revokeObjectURL(url);
    }
