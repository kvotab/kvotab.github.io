/* PyLAB's app designer: an app's window laid out with the mouse, its
   components' properties and callbacks set in an inspector, and the app
   written as a class file (classdef ... < matlab.apps.AppBase) that runs as
   any other program. The layout is kept in a comment at the end of the file,
   so that the designer opens the app again; the callbacks' code is read
   back from the class, so what was written in the Editor stays. */
(() => {
  'use strict';
  const { el } = PL;
  const U = PL.util;

  // kind: the palette's label, the call that makes it, its class, size, properties and callback
  const KINDS = {
    button: { label: 'Button', make: "uibutton(P, 'push')", cls: 'matlab.ui.control.Button', w: 100, h: 22, props: { Text: 'Button' }, cb: ['ButtonPushedFcn', 'ButtonPushed'] },
    label: { label: 'Label', make: 'uilabel(P)', cls: 'matlab.ui.control.Label', w: 60, h: 22, props: { Text: 'Label' } },
    editfield: { label: 'Edit Field (Text)', make: "uieditfield(P, 'text')", cls: 'matlab.ui.control.EditField', w: 100, h: 22, props: { Value: '' }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    numericeditfield: { label: 'Edit Field (Numeric)', make: "uieditfield(P, 'numeric')", cls: 'matlab.ui.control.NumericEditField', w: 100, h: 22, props: { Value: 0, Limits: '-Inf Inf' }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    textarea: { label: 'Text Area', make: 'uitextarea(P)', cls: 'matlab.ui.control.TextArea', w: 150, h: 60, props: { Value: '' }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    dropdown: { label: 'Drop Down', make: 'uidropdown(P)', cls: 'matlab.ui.control.DropDown', w: 100, h: 22, props: { Items: 'Option 1, Option 2, Option 3', Value: 'Option 1' }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    listbox: { label: 'List Box', make: 'uilistbox(P)', cls: 'matlab.ui.control.ListBox', w: 100, h: 74, props: { Items: 'Item 1, Item 2, Item 3, Item 4', Value: 'Item 1' }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    checkbox: { label: 'Check Box', make: 'uicheckbox(P)', cls: 'matlab.ui.control.CheckBox', w: 90, h: 22, props: { Text: 'Check Box', Value: false }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    statebutton: { label: 'State Button', make: "uibutton(P, 'state')", cls: 'matlab.ui.control.StateButton', w: 100, h: 22, props: { Text: 'State Button', Value: false }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    switch: { label: 'Switch', make: "uiswitch(P, 'slider')", cls: 'matlab.ui.control.Switch', w: 45, h: 20, props: { Items: 'Off, On', Value: 'Off' }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    slider: { label: 'Slider', make: 'uislider(P)', cls: 'matlab.ui.control.Slider', w: 150, h: 3, props: { Limits: '0 100', Value: 0 }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    spinner: { label: 'Spinner', make: 'uispinner(P)', cls: 'matlab.ui.control.Spinner', w: 100, h: 22, props: { Value: 0, Step: 1 }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    knob: { label: 'Knob', make: "uiknob(P, 'continuous')", cls: 'matlab.ui.control.Knob', w: 60, h: 60, props: { Limits: '0 100', Value: 0 }, cb: ['ValueChangedFcn', 'ValueChanged'] },
    gauge: { label: 'Gauge', make: "uigauge(P, 'circular')", cls: 'matlab.ui.control.Gauge', w: 120, h: 120, props: { Limits: '0 100', Value: 0 } },
    lamp: { label: 'Lamp', make: 'uilamp(P)', cls: 'matlab.ui.control.Lamp', w: 20, h: 20, props: { Color: '0 1 0' } },
    hyperlink: { label: 'Hyperlink', make: 'uihyperlink(P)', cls: 'matlab.ui.control.Hyperlink', w: 70, h: 22, props: { Text: 'Hyperlink', URL: '' } },
    axes: { label: 'Axes', make: 'uiaxes(P)', cls: 'matlab.ui.control.UIAxes', w: 300, h: 185, props: { Title: 'Title', XLabel: 'X', YLabel: 'Y' } },
    panel: { label: 'Panel', make: 'uipanel(P)', cls: 'matlab.ui.container.Panel', w: 260, h: 220, props: { Title: 'Panel' } },
  };
  // what each property is: text, number, logical, a list or numbers
  const PROPKIND = { Text: 'text', Value: 'value', Items: 'list', Limits: 'nums', Step: 'num', Color: 'nums', URL: 'text', Title: 'text', XLabel: 'text', YLabel: 'text' };
  const MARK = 'PyLAB app designer layout';

  const q = (s) => `'${String(s).replace(/'/g, "''")}'`;

  class Designer {
    constructor() {
      this.app = null;
      this.sel = null;
    }

    blank() {
      return { name: 'MyApp', title: 'My App', w: 640, h: 480, startup: '', comps: [] };
    }

    /* Whether a file's text is an app made here (it has the layout comment). */
    isApp(text) { return String(text).includes(`%{\n${MARK}`); }

    async open(path) {
      this.path = path;
      this.app = this.blank();
      this.bodies = {};
      if (path) {
        try {
          // an Editor tab's text if the file is open there (its callbacks may not be saved yet)
          const open = PL.app.docText(path);
          const text = open != null ? open : await PL.engine.fs('read', { path });
          this.read(String(text));
        } catch (e) {
          PL.app.cmd.write(`The app file ${path} could not be read: ${e.message || e}\n`, 'err');
          return;
        }
        this.app.name = path.split('/').pop().replace(/\.m$/, '');
      }
      this.build();
      this.draw();
    }

    /* An app file made here: its layout from the comment at its end, its
       callbacks' code from the class. */
    read(text) {
      const at = text.indexOf(`%{\n${MARK}`);
      if (at < 0) throw new Error('it was not made in the app designer (it has no layout comment)');
      const json = text.slice(text.indexOf('\n', text.indexOf('\n', at) + 1) + 1, text.indexOf('\n%}', at));
      const lay = JSON.parse(json);
      Object.assign(this.app, lay);
      this.bodies = this.callbackBodies(text);
      if (this.bodies.startupFcn != null) this.app.startup = this.bodies.startupFcn;
    }

    callbackBodies(text) {
      const out = {};
      const lines = text.split('\n');
      for (let i = 0; i < lines.length; i++) {
        const m = /^(\s*)function\s+(\w+)\s*\(app(?:,\s*(?:event|varargin))?\)\s*$/.exec(lines[i]);
        if (!m || ['createComponents', 'delete'].includes(m[2])) continue;
        const ind = m[1];
        const body = [];
        let j = i + 1;
        for (; j < lines.length; j++) {
          if (lines[j] === `${ind}end` || lines[j].replace(/\s+$/, '') === `${ind}end`) break;
          body.push(lines[j].startsWith(`${ind}    `) ? lines[j].slice(ind.length + 4) : lines[j].trimStart());
        }
        out[m[2]] = body.join('\n').replace(/\s+$/, '');
        i = j;
      }
      return out;
    }

    /* ---- the class file -------------------------------------------------------------- */
    code() {
      const A = this.app;
      const names = A.comps.map((c) => c.name);
      const w = Math.max(...['UIFigure', ...names].map((n) => n.length));
      const P = [];
      P.push(`classdef ${A.name} < matlab.apps.AppBase`);
      P.push(`    % ${A.name.toUpperCase()}  An app laid out in PyLAB's app designer. Run it by its name;`);
      P.push('    % the callbacks below are yours to write, the rest the designer writes again.');
      P.push('');
      P.push("    % The app's window and components");
      P.push('    properties (Access = public)');
      P.push(`        ${'UIFigure'.padEnd(w)}  matlab.ui.Figure`);
      for (const c of A.comps) P.push(`        ${c.name.padEnd(w)}  ${KINDS[c.kind].cls}`);
      P.push('    end');
      const cbs = A.comps.filter((c) => c.callback && KINDS[c.kind].cb);
      if (cbs.length || A.startup) {
        P.push('');
        P.push('    % The callbacks: what happens when the components are used');
        P.push('    methods (Access = private)');
        if (A.startup) {
          P.push('');
          P.push('        % Runs once the window is made');
          P.push('        function startupFcn(app)');
          for (const l of A.startup.split('\n')) P.push(l ? `            ${l}` : '');
          P.push('        end');
        }
        for (const c of cbs) {
          P.push('');
          P.push(`        % ${KINDS[c.kind].cb[0]} of ${c.name}`);
          P.push(`        function ${c.callback}(app, event)`);
          const body = this.bodies[c.callback] ?? c.body ?? '';
          for (const l of body.split('\n')) P.push(l ? `            ${l}` : '');
          P.push('        end');
        }
        P.push('    end');
      }
      P.push('');
      P.push('    % Making the window and its components');
      P.push('    methods (Access = private)');
      P.push('');
      P.push('        function createComponents(app)');
      P.push("            app.UIFigure = uifigure('Visible', 'off');");
      P.push(`            app.UIFigure.Position = [100 100 ${A.w} ${A.h}];`);
      P.push(`            app.UIFigure.Name = ${q(A.title)};`);
      for (const c of A.comps) {
        const K = KINDS[c.kind];
        const parent = c.parent ? `app.${c.parent}` : 'app.UIFigure';
        P.push('');
        P.push(`            app.${c.name} = ${K.make.replace('P', parent)};`);
        for (const [k, v] of Object.entries(c.props)) {
          const line = this.propLine(c, k, v);
          if (line) P.push(`            ${line}`);
        }
        if (c.kind !== 'axes') P.push(`            app.${c.name}.Position = [${[c.x, c.y, c.w, c.h].map(Math.round).join(' ')}];`);
        else P.push(`            app.${c.name}.Position = [${[c.x + 45, c.y + 38, Math.max(10, c.w - 60), Math.max(10, c.h - 66)].map(Math.round).join(' ')}];`);
        if (c.callback && K.cb) P.push(`            app.${c.name}.${K.cb[0]} = createCallbackFcn(app, @${c.callback}, true);`);
      }
      P.push('');
      P.push("            app.UIFigure.Visible = 'on';");
      P.push('        end');
      P.push('    end');
      P.push('');
      P.push('    % Making and deleting the app');
      P.push('    methods (Access = public)');
      P.push('');
      P.push(`        function app = ${A.name}`);
      P.push('            createComponents(app)');
      P.push('            registerApp(app, app.UIFigure)');
      if (A.startup) P.push('            runStartupFcn(app, @startupFcn)');
      P.push('            if nargout == 0');
      P.push('                clear app');
      P.push('            end');
      P.push('        end');
      P.push('');
      P.push('        function delete(app)');
      P.push('            delete(app.UIFigure)');
      P.push('        end');
      P.push('    end');
      P.push('end');
      P.push('');
      const lay = { title: A.title, w: A.w, h: A.h, comps: A.comps.map(({ body, ...rest }) => rest) };
      P.push(`%{\n${MARK} (the designer reads this to open the app again)\n${JSON.stringify(lay)}\n%}`);
      return `${P.join('\n')}\n`;
    }

    propLine(c, k, v) {
      const t = PROPKIND[k];
      const target = `app.${c.name}.${k}`;
      if (c.kind === 'axes' && ['Title', 'XLabel', 'YLabel'].includes(k)) {
        const fn = { Title: 'title', XLabel: 'xlabel', YLabel: 'ylabel' }[k];
        return v ? `${fn}(app.${c.name}, ${q(v)})` : null;
      }
      if (c.kind === 'panel' && k === 'Title') return `${target} = ${q(v)};`;
      if (t === 'list') return `${target} = {${String(v).split(',').map((s) => q(s.trim())).filter((s) => s !== "''").join(', ')}};`;
      if (t === 'nums') return `${target} = [${String(v).trim()}];`;
      if (t === 'num') return `${target} = ${Number(v) || 0};`;
      if (k === 'Value') {
        if (typeof v === 'boolean') return `${target} = ${v ? 'true' : 'false'};`;
        if (['numericeditfield', 'slider', 'spinner', 'knob', 'gauge'].includes(c.kind)) return `${target} = ${Number(v) || 0};`;
        if (c.kind === 'textarea') return v ? `${target} = {${String(v).split('\n').map(q).join('; ')}};` : null;
        return `${target} = ${q(v)};`;
      }
      return `${target} = ${q(v)};`;
    }

    /* ---- the window ------------------------------------------------------------------ */
    build() {
      if (this.el) this.el.remove();
      const bar = el('div', { class: 'pl-ad-bar' },
        el('strong', null, 'App Designer'),
        this.nameIn = el('input', { type: 'text', class: 'pl-ad-name', 'aria-label': 'App name', spellcheck: 'false' }),
        el('span', { class: 'pl-ad-grow' }),
        this.btn('Save', () => this.save()),
        this.btn('Run', () => this.run()),
        this.btn('Code', () => this.showCode()),
        this.btn('Close', () => this.close()));
      this.nameIn.value = this.app.name;
      this.nameIn.addEventListener('change', () => {
        const v = this.nameIn.value.trim();
        if (/^[A-Za-z]\w{0,62}$/.test(v)) { this.app.name = v; this.path = null; } else this.nameIn.value = this.app.name;
      });
      this.palette = el('div', { class: 'pl-ad-palette', role: 'list', 'aria-label': 'Components' },
        ...Object.entries(KINDS).map(([k, K]) => {
          const b = el('button', { type: 'button', draggable: 'true', role: 'listitem' }, K.label);
          b.addEventListener('click', () => this.add(k));
          b.addEventListener('dragstart', (ev) => ev.dataTransfer.setData('text/x-pylab-component', k));
          return b;
        }));
      this.stage = el('div', { class: 'pl-ad-stage' });
      this.canvas = el('div', { class: 'pl-ad-canvas', tabindex: '0', 'aria-label': "The app's window" });
      this.stage.append(this.canvas);
      this.inspector = el('div', { class: 'pl-ad-inspector' });
      this.el = el('div', { class: 'pl-ad', role: 'dialog', 'aria-label': 'App Designer' }, bar, el('div', { class: 'pl-ad-body' }, this.palette, this.stage, this.inspector));
      document.body.append(this.el);
      this.canvas.addEventListener('pointerdown', (ev) => { if (ev.target === this.canvas) { this.select(null); } });
      this.canvas.addEventListener('dragover', (ev) => { if ([...ev.dataTransfer.types].includes('text/x-pylab-component')) ev.preventDefault(); });
      this.canvas.addEventListener('drop', (ev) => {
        const k = ev.dataTransfer.getData('text/x-pylab-component');
        if (!k) return;
        ev.preventDefault();
        const r = this.canvas.getBoundingClientRect();
        this.add(k, ev.clientX - r.left, r.bottom - ev.clientY);
      });
      this.canvas.addEventListener('keydown', (ev) => this.key(ev));
    }

    btn(label, fn) {
      const b = el('button', { type: 'button' }, label);
      b.addEventListener('click', fn);
      return b;
    }

    close() {
      if (this.el) this.el.remove();
      this.el = null;
    }

    uniqueName(base) {
      const taken = new Set(['UIFigure', ...this.app.comps.map((c) => c.name)]);
      for (let i = 1; ; i++) {
        const n = i === 1 && !taken.has(base) ? base : `${base}${i}`;
        if (!taken.has(n)) return n;
      }
    }

    add(kind, x, y) {
      const K = KINDS[kind];
      const base = K.label.replace(/\(.*\)/, '').replace(/[^A-Za-z]/g, '');
      const name = this.uniqueName(base);
      const c = { kind, name, x: 0, y: 0, w: K.w, h: K.h, props: { ...K.props } };
      const n = this.app.comps.length;
      c.x = x != null ? Math.round(x - K.w / 2) : 20 + (n % 6) * 18;
      c.y = y != null ? Math.round(y - K.h / 2) : this.app.h - 40 - K.h - (n % 6) * 18;
      this.clamp(c);
      if (K.cb) c.callback = '';
      this.app.comps.push(c);
      this.select(c);
      this.draw();
    }

    clamp(c) {
      c.w = Math.max(4, Math.min(c.w, this.app.w));
      c.h = Math.max(3, Math.min(c.h, this.app.h));
      c.x = Math.max(0, Math.min(c.x, this.app.w - c.w));
      c.y = Math.max(0, Math.min(c.y, this.app.h - c.h));
    }

    select(c) {
      this.sel = c;
      this.draw();
      this.inspect();
    }

    key(ev) {
      const c = this.sel;
      if (!c) return;
      const step = ev.shiftKey ? 10 : 1;
      const mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[ev.key];
      if (mv) {
        ev.preventDefault();
        c.x += mv[0];
        c.y += mv[1];
        this.clamp(c);
        this.draw();
        this.inspect();
      } else if (ev.key === 'Delete' || ev.key === 'Backspace') {
        ev.preventDefault();
        this.app.comps = this.app.comps.filter((o) => o !== c && o.parent !== c.name);
        this.select(null);
      }
    }

    /* The window and its components as they will look (roughly), with handles on the selected one. */
    draw() {
      const A = this.app;
      const cv = this.canvas;
      cv.style.width = `${A.w}px`;
      cv.style.height = `${A.h}px`;
      cv.replaceChildren(...A.comps.map((c) => this.preview(c)));
    }

    preview(c) {
      const K = KINDS[c.kind];
      const p = c.props;
      let inner;
      switch (c.kind) {
        case 'button': case 'statebutton': inner = el('div', { class: 'pv pv-btn' }, p.Text || ''); break;
        case 'label': case 'hyperlink': inner = el('div', { class: `pv pv-label${c.kind === 'hyperlink' ? ' pv-link' : ''}` }, p.Text || ''); break;
        case 'editfield': case 'numericeditfield': case 'spinner': inner = el('div', { class: 'pv pv-edit' }, String(p.Value ?? '')); break;
        case 'textarea': inner = el('div', { class: 'pv pv-edit pv-area' }, String(p.Value ?? '')); break;
        case 'dropdown': inner = el('div', { class: 'pv pv-edit pv-drop' }, String(p.Value ?? '')); break;
        case 'listbox': inner = el('div', { class: 'pv pv-edit pv-list' }, ...String(p.Items || '').split(',').map((s) => el('div', null, s.trim()))); break;
        case 'checkbox': inner = el('div', { class: 'pv pv-check' }, el('span', { class: 'box' }), p.Text || ''); break;
        case 'switch': inner = el('div', { class: 'pv pv-switch' }, el('span', { class: 'track' })); break;
        case 'slider': inner = el('div', { class: 'pv pv-slider' }); break;
        case 'knob': case 'gauge': case 'lamp': inner = el('div', { class: `pv pv-round pv-${c.kind}` }); break;
        case 'axes': inner = el('div', { class: 'pv pv-axes' }, el('span', null, p.Title || '')); break;
        case 'panel': inner = el('div', { class: 'pv pv-panel' }, el('span', null, p.Title || '')); break;
        default: inner = el('div', { class: 'pv' }, K.label);
      }
      const box = el('div', { class: `pl-ad-comp${c === this.sel ? ' is-sel' : ''}`, title: `${c.name} (${K.label})` }, inner);
      Object.assign(box.style, { left: `${c.x}px`, bottom: `${c.y}px`, width: `${c.w}px`, height: `${Math.max(c.h, c.kind === 'slider' ? 16 : c.h)}px` });
      box.addEventListener('pointerdown', (ev) => this.grab(ev, c, 'move'));
      if (c === this.sel) {
        for (const h of ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']) {
          const hd = el('span', { class: `hd hd-${h}` });
          hd.addEventListener('pointerdown', (ev) => { ev.stopPropagation(); this.grab(ev, c, h); });
          box.append(hd);
        }
      }
      return box;
    }

    /* Moving or resizing with the mouse, on a grid of 2 pixels. */
    grab(ev, c, how) {
      if (ev.button !== 0) return;
      ev.preventDefault();
      if (this.sel !== c) this.select(c);
      this.canvas.focus({ preventScroll: true });
      const start = { x: ev.clientX, y: ev.clientY, c: { ...c } };
      const move = (e) => {
        const dx = Math.round((e.clientX - start.x) / 2) * 2;
        const dy = -Math.round((e.clientY - start.y) / 2) * 2;
        const s = start.c;
        if (how === 'move') { c.x = s.x + dx; c.y = s.y + dy; } else {
          if (how.includes('e')) c.w = s.w + dx;
          if (how.includes('w')) { c.x = s.x + dx; c.w = s.w - dx; }
          if (how.includes('n')) c.h = s.h + dy;
          if (how.includes('s')) { c.y = s.y + dy; c.h = s.h - dy; }
        }
        this.clamp(c);
        this.draw();
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        this.inspect();
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    }

    /* ---- the inspector ------------------------------------------------------------- */
    inspect() {
      const c = this.sel;
      const A = this.app;
      const rows = [];
      const field = (label, value, set, attrs = {}) => {
        const i = el('input', Object.assign({ type: 'text', spellcheck: 'false', value: String(value ?? '') }, attrs));
        i.addEventListener('change', () => { set(i.value); this.draw(); });
        rows.push(el('label', { class: 'pl-ad-row' }, el('span', null, label), i));
        return i;
      };
      if (!c) {
        rows.push(el('h3', null, "The app's window"));
        field('Title', A.title, (v) => { A.title = v; });
        field('Width', A.w, (v) => { A.w = Math.max(100, Number(v) || A.w); A.comps.forEach((o) => this.clamp(o)); });
        field('Height', A.h, (v) => { A.h = Math.max(80, Number(v) || A.h); A.comps.forEach((o) => this.clamp(o)); });
        const ta = el('textarea', { spellcheck: 'false', rows: '6', 'aria-label': 'Startup code' });
        ta.value = A.startup || '';
        ta.addEventListener('change', () => { A.startup = ta.value.replace(/\s+$/, ''); });
        rows.push(el('div', { class: 'pl-ad-row pl-ad-code' }, el('span', null, 'Code to run at the start (startupFcn, with app)'), ta));
        rows.push(el('p', { class: 'pl-ad-hint' }, 'Click a component to add it, or drag it onto the window. Arrow keys move the selected one (Shift: 10 pixels); Delete removes it.'));
      } else {
        const K = KINDS[c.kind];
        rows.push(el('h3', null, K.label));
        field('Name', c.name, (v) => {
          v = v.trim();
          if (/^[A-Za-z]\w{0,62}$/.test(v) && !A.comps.some((o) => o !== c && o.name === v) && v !== 'UIFigure') {
            for (const o of A.comps) if (o.parent === c.name) o.parent = v;
            c.name = v;
          }
          this.inspect();
        });
        field('Position', [c.x, c.y, c.w, c.h].join(' '), (v) => {
          const n = v.trim().split(/[\s,]+/).map(Number);
          if (n.length === 4 && n.every(Number.isFinite)) { [c.x, c.y, c.w, c.h] = n; this.clamp(c); }
          this.inspect();
        });
        for (const [k, v] of Object.entries(c.props)) {
          if (typeof v === 'boolean') {
            const cb = el('input', { type: 'checkbox' });
            cb.checked = v;
            cb.addEventListener('change', () => { c.props[k] = cb.checked; this.draw(); });
            rows.push(el('label', { class: 'pl-ad-row' }, el('span', null, k), cb));
          } else field(k + (PROPKIND[k] === 'list' ? ' (comma-separated)' : PROPKIND[k] === 'nums' ? ' (numbers)' : ''), v, (nv) => { c.props[k] = nv; });
        }
        if (K.cb) {
          const placeholder = `${c.name}${K.cb[1]}`;
          field(`${K.cb[0]}`, c.callback || '', (v) => {
            v = v.trim();
            c.callback = /^[A-Za-z]\w{0,62}$/.test(v) ? v : '';
            this.inspect();
          }, { placeholder: `${placeholder} (a name makes the callback)` });
          if (c.callback) {
            const ta = el('textarea', { spellcheck: 'false', rows: '8', 'aria-label': 'Callback code' });
            ta.value = this.bodies[c.callback] ?? c.body ?? '';
            ta.addEventListener('change', () => { this.bodies[c.callback] = ta.value.replace(/\s+$/, ''); });
            rows.push(el('div', { class: 'pl-ad-row pl-ad-code' }, el('span', null, `function ${c.callback}(app, event)`), ta));
          } else {
            const b = this.btn(`Add a callback: ${placeholder}`, () => { c.callback = this.uniqueName(placeholder); this.inspect(); });
            rows.push(b);
          }
        }
      }
      this.inspector.replaceChildren(...rows);
    }

    /* ---- saving and running ---------------------------------------------------------- */
    async save() {
      const path = this.path || `${PL.app.cwd}/${this.app.name}.m`;
      if (!this.path) {
        const exists = await PL.engine.fs('exists', { path });
        if (exists && !window.confirm(`${this.app.name}.m is there already. Write over it?`)) return null;
      }
      await PL.engine.fs('write', { path, data: this.code() });
      this.path = path;
      // an Editor tab on the file takes the new code (the designer read its callbacks from it)
      await PL.app.reloadDoc(path, true);
      await PL.app.folder.refresh();
      PL.app.cmd.write(`Saved the app: ${path}\n`, 'out');
      return path;
    }

    async run() {
      const path = await this.save();
      if (!path) return;
      await PL.app.runCommand(this.app.name);
    }

    async showCode() {
      const path = await this.save();
      if (!path) return;
      await PL.app.openFile(path);
      this.close();
      U.toast('Design App on the EDITOR tab opens the layout again.', 6000);
    }
  }

  PL.designer = new Designer();
})();
