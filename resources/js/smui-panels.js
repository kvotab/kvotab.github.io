/* ==========================================================================
   SMUI.HTML: THE TABLE, COLUMNS AND ROWS PANELS

   The strip left of the grid, as in a JMP data table:

     Table    the open tables, the current one's name and where it came from
     Columns  every column with its modeling type; click the icon to change
              the type, click a name to select the column, drag names to
              reorder them or onto a launch dialog's role, right click for
              the column menu, double click for Column Info
     Rows     how many rows are selected, excluded, hidden and labeled;
              click a line to select those rows
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, typeIcon, TYPE_LABEL } = SM.util;

  class Panels {
    constructor(host, app) {
      this.app = app;
      this.table = null;
      this.off = null;

      // Table
      this.tableSelect = el('select', { class: 'sm-tablename', 'aria-label': 'Open tables' });
      this.tableSelect.addEventListener('change', () => app.showTable(this.tableSelect.value));
      this.meta = el('div', { class: 'sm-tablemeta' });
      const tmenu = el('button', { type: 'button', class: 'sm-ob-menu', 'aria-label': 'Table options', 'aria-haspopup': 'menu' }, redTriangle());
      tmenu.addEventListener('click', () => SM.ui.menu(app.tableMenu(), tmenu, { returnFocus: tmenu }));
      this.pTable = el('div', { class: 'sm-panel sm-panel-table' },
        el('h3', null, tmenu, 'Table', el('span', { class: 'sm-grow' }), infoSlot('panel:table')),
        el('div', { class: 'sm-tablebox' }, this.tableSelect, this.meta));

      // Columns
      this.colCount = el('span', { class: 'sm-count' });
      this.colFilter = el('input', { type: 'search', class: 'sm-colfilter', placeholder: 'Filter', 'aria-label': 'Filter columns' });
      this.colFilter.addEventListener('input', () => this.renderColumns());
      this.colList = el('ul', { class: 'sm-collist', role: 'listbox', 'aria-label': 'Columns', 'aria-multiselectable': 'true' });
      const cmenu = el('button', { type: 'button', class: 'sm-ob-menu', 'aria-label': 'Columns options', 'aria-haspopup': 'menu' }, redTriangle());
      cmenu.addEventListener('click', () => SM.ui.menu(app.colsMenuItems(), cmenu, { returnFocus: cmenu }));
      this.pCols = el('div', { class: 'sm-panel sm-panel-cols' },
        el('h3', null, cmenu, 'Columns', this.colCount, el('span', { class: 'sm-grow' }), infoSlot('panel:columns')),
        this.colFilter, this.colList);
      this._wireColumns();

      // Rows
      this.rowTable = el('table', { class: 'sm-rowcounts' });
      const rmenu = el('button', { type: 'button', class: 'sm-ob-menu', 'aria-label': 'Rows options', 'aria-haspopup': 'menu' }, redTriangle());
      rmenu.addEventListener('click', () => SM.ui.menu(app.rowsMenuItems(), rmenu, { returnFocus: rmenu }));
      this.pRows = el('div', { class: 'sm-panel sm-panel-rows' },
        el('h3', null, rmenu, 'Rows', el('span', { class: 'sm-grow' }), infoSlot('panel:rows')), this.rowTable);

      // Rows > Data Filter, docked here while it is open.
      this.pFilter = el('div', { class: 'sm-panel sm-panel-filter', hidden: true });

      host.append(this.pTable, this.pCols, this.pFilter, this.pRows);
    }

    /* The global data filter of a table: its matching rows are selected,
       and optionally the others hidden and excluded, in the table itself. */
    renderDataFilter() {
      const t = this.table;
      const df = t && t.dataFilter;
      this.pFilter.hidden = !df;
      if (!df) { this.pFilter.replaceChildren(); return; }
      const all = () => Array.from({ length: t.nrows }, (_, i) => i);
      const apply = () => {
        const active = SM.report.filterActive(df.entries);
        const match = active ? new Set(SM.report.filterRows(t, df.entries, all())) : null;
        if (df.select) t.select(active ? [...match] : []);
        const set = (flag, on) => {
          if (!on) return;
          for (let i = 0; i < t.nrows; i++) { const bit = SM.table.STATE_BIT[flag]; if (active && !match.has(i)) t.state[i] |= bit; else t.state[i] &= ~bit; }
          t.emit('rowstate', { kind: flag });
        };
        set('hidden', df.show);
        set('excluded', df.include);
      };
      const mode = (key, label) => {
        const i = el('input', { type: 'checkbox' });
        i.checked = !!df[key];
        i.addEventListener('change', () => {
          df[key] = i.checked;
          if (!i.checked) {
            if (key === 'select') t.select([]);
            else { t.setState(all(), key === 'show' ? 'hidden' : 'excluded', false); }
          }
          apply();
        });
        return el('label', null, i, label);
      };
      const modes = el('div', { class: 'sm-filter-modes' }, mode('select', 'Select'), mode('show', 'Show'), mode('include', 'Include'));
      SM.report.renderFilter(this.pFilter, t, df.entries, {
        title: 'Data Filter', info: 'rows:datafilter', extra: modes, base: all,
        onClose: () => this.app.toggleDataFilter(false),
        onChange: apply,
      });
    }

    setTable(t) {
      if (this.off) this.off.forEach((f) => f());
      this.table = t;
      this.off = t ? [
        t.on('schema', () => { this.renderColumns(); this.renderTable(); }),
        t.on('data', () => { this.renderTable(); this.renderRows(); }),
        t.on('rowstate', () => this.renderRows()),
      ] : null;
      this.renderTable();
      this.renderColumns();
      this.renderRows();
      this.renderDataFilter();
    }

    renderTable() {
      const app = this.app;
      this.tableSelect.replaceChildren(...app.tables.map((t) => el('option', { value: t.id, text: t.name, selected: t === this.table ? true : null })));
      this.tableSelect.disabled = !app.tables.length;
      if (!app.tables.length) this.tableSelect.append(el('option', { text: 'No table open' }));
      const t = this.table;
      this.meta.replaceChildren();
      if (!t) return;
      this.meta.append(el('div', { text: `${t.nrows} rows, ${t.columns.length} columns` }));
      if (t.source) this.meta.append(el('div', { text: t.source }));
      if (t.notes) this.meta.append(el('div', { text: t.notes.length > 180 ? `${t.notes.slice(0, 180)}…` : t.notes, title: t.notes }));
    }

    renderColumns() {
      const t = this.table;
      this.colList.replaceChildren();
      if (!t) { this.colCount.textContent = ''; return; }
      const sel = new Set(this.app.selectedColumns().map((c) => c.id));
      this.colCount.textContent = `${sel.size ? `${sel.size}/` : ''}${t.columns.length}`;
      const f = this.colFilter.value.trim().toLowerCase();
      for (const c of t.columns) {
        if (f && !c.name.toLowerCase().includes(f)) continue;
        const tb = el('button', { type: 'button', class: 'sm-typebtn', 'aria-label': `${c.name}: ${TYPE_LABEL[c.modelingType]}. Change the modeling type`, dataset: { type: c.id } }, typeIcon(c.modelingType));
        const flags = [c.formula ? 'ƒ' : '', c.role === 'label' ? 'label' : '', c.isNumeric ? '' : 'abc'].filter(Boolean).join(' ');
        const li = el('li', { role: 'option', draggable: 'true', dataset: { id: c.id }, 'aria-selected': String(sel.has(c.id)) },
          tb, el('span', { class: 'sm-colname', text: c.name }), flags ? el('span', { class: 'sm-colflag', text: flags }) : null);
        if (sel.has(c.id)) li.classList.add('is-selected');
        li.title = `${c.name}: ${TYPE_LABEL[c.modelingType]}, ${c.dataType}${c.notes ? `. ${c.notes}` : ''}`;
        this.colList.append(li);
      }
    }

    _wireColumns() {
      const list = this.colList;
      let anchor = null;
      list.addEventListener('click', (ev) => {
        const t = this.table;
        if (!t) return;
        const tb = ev.target.closest('.sm-typebtn');
        if (tb) {
          const c = t.col(tb.dataset.type);
          SM.ui.menu(['continuous', 'ordinal', 'nominal'].map((m) => ({
            label: TYPE_LABEL[m], checked: c.modelingType === m, disabled: m === 'continuous' && !c.isNumeric,
            title: m === 'continuous' && !c.isNumeric ? 'A character column cannot be continuous; change its data type in Column Info' : null,
            action: () => t.setType(c.id, { modelingType: m }),
          })), tb, { returnFocus: tb });
          return;
        }
        const li = ev.target.closest('li');
        if (!li) return;
        const g = this.app.grid;
        const id = li.dataset.id;
        if (ev.shiftKey && anchor) {
          const ids = t.columns.map((c) => c.id);
          const a = ids.indexOf(anchor), b = ids.indexOf(id);
          for (let k = Math.min(a, b); k <= Math.max(a, b); k++) g.colSel.add(ids[k]);
        } else if (ev.metaKey || ev.ctrlKey) {
          if (g.colSel.has(id)) g.colSel.delete(id); else g.colSel.add(id);
          anchor = id;
        } else {
          const only = g.colSel.size === 1 && g.colSel.has(id);
          g.colSel.clear();
          if (!only) g.colSel.add(id);
          anchor = id;
        }
        g.refresh();
        this.renderColumns();
        this.app.emit('columnselection', this.app.selectedColumns());
      });
      list.addEventListener('dblclick', (ev) => {
        const li = ev.target.closest('li');
        if (li && !ev.target.closest('.sm-typebtn')) this.app.columnInfo(this.table.col(li.dataset.id));
      });
      list.addEventListener('contextmenu', (ev) => {
        const li = ev.target.closest('li');
        if (!li) return;
        ev.preventDefault();
        const g = this.app.grid;
        if (!g.colSel.has(li.dataset.id)) { g.colSel.clear(); g.colSel.add(li.dataset.id); g.refresh(); this.renderColumns(); }
        SM.ui.menu(this.app.columnMenu(this.table.col(li.dataset.id)), { x: ev.clientX, y: ev.clientY });
      });
      // Drag to reorder, or onto a launch dialog's role.
      let dragId = null;
      list.addEventListener('dragstart', (ev) => {
        const li = ev.target.closest('li');
        if (!li) return;
        dragId = li.dataset.id;
        const g = this.app.grid;
        const ids = g.colSel.has(dragId) ? [...g.colSel] : [dragId];
        ev.dataTransfer.setData(SM.launch.MIME, JSON.stringify(ids));
        ev.dataTransfer.setData('text/plain', ids.map((id) => this.table.col(id).name).join('\n'));
        ev.dataTransfer.effectAllowed = 'copyMove';
      });
      list.addEventListener('dragover', (ev) => {
        if (!dragId) return;
        const li = ev.target.closest('li');
        if (!li) return;
        ev.preventDefault();
        list.querySelectorAll('.drop-above').forEach((x) => x.classList.remove('drop-above'));
        li.classList.add('drop-above');
      });
      list.addEventListener('dragleave', () => list.querySelectorAll('.drop-above').forEach((x) => x.classList.remove('drop-above')));
      list.addEventListener('drop', (ev) => {
        const li = ev.target.closest('li');
        list.querySelectorAll('.drop-above').forEach((x) => x.classList.remove('drop-above'));
        if (!dragId || !li || li.dataset.id === dragId) return;
        ev.preventDefault();
        const t = this.table;
        t.moveColumn(dragId, t.colIndex(li.dataset.id) - (t.colIndex(dragId) < t.colIndex(li.dataset.id) ? 1 : 0));
      });
      list.addEventListener('dragend', () => { dragId = null; });
    }

    renderRows() {
      const t = this.table;
      this.rowTable.replaceChildren();
      if (!t) return;
      const c = t.counts();
      const lines = [['All rows', c.all, null], ['Selected', c.selected, 'selected'], ['Excluded', c.excluded, 'excluded'], ['Hidden', c.hidden, 'hidden'], ['Labeled', c.labeled, 'labeled']];
      for (const [label, n, flag] of lines) {
        const tr = el('tr', { class: n ? '' : 'is-zero' }, el('td', { text: label }), el('td', { text: String(n) }));
        if (n && flag !== 'selected') {
          tr.style.cursor = 'pointer';
          tr.title = flag ? `Select the ${label.toLowerCase()} rows` : 'Select all rows';
          tr.addEventListener('click', () => t.select(flag ? t.rowsWith(flag) : Array.from({ length: t.nrows }, (_, i) => i)));
        }
        this.rowTable.append(tr);
      }
    }
  }

  function redTriangle() {
    return SM.util.svg('svg', { viewBox: '0 0 10 10', width: 11, height: 11, 'aria-hidden': 'true' }, SM.util.svg('path', { d: 'M1.5 2.5 L8.5 2.5 L5 8.5 Z', fill: 'currentColor' }));
  }

  function infoSlot(key) {
    return typeof KvotInfo !== 'undefined' ? KvotInfo.slot(key) : null;
  }

  SM.panels = Object.freeze({ Panels, redTriangle });
}(typeof self !== 'undefined' ? self : this));
