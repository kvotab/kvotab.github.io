"""Classes of the language's own (classdef files) and apps, run natively:
handle and value classes, constructors and nargin, properties (defaults,
Constant, Dependent with get and set methods), methods called both ways,
static methods, inheritance with super calls, operator and builtin
overloading, events and listeners, delete and isvalid, display; the
components of apps (their classes and Types, defaults, values checked,
events from the page queueing callbacks with their data), grid layouts
placing children, uifigure's hidden handle, and an app class written as
App Designer writes them (and as PyLAB's designer writes them) running;
a value class's set method, property validation, arguments blocks,
enumerations, packages and import.

    python3 test_class.py          (from any folder)
"""
import asyncio
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab import uievents as E  # noqa: E402
from plab.values import Char, Cell, Struct  # noqa: E402
from plab.graphics_base import serialize_figure  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-class-')


def write(name, text):
    with open(os.path.join(TMP, name), 'w', encoding='utf-8') as fh:
        fh.write(text)
    R.bump_epoch()


def run(code):
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
    return R.BASE, R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def val(v):
    if isinstance(v, Char):
        return v.str()
    if isinstance(v, np.ndarray):
        return v.tolist() if v.size != 1 else v.item()
    return v


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def refused(label, code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    return C(label, words in val(W['e']), val(W['e']))


write('Account.m', """classdef Account < handle
    % ACCOUNT  A handle class with an event.
    properties
        Owner char = 'nobody'
        Balance (1,1) double = 0   % money
    end
    properties (Constant)
        Rate = 0.02
    end
    properties (Dependent)
        Interest
    end
    events
        Overdrawn
    end
    methods
        function obj = Account(owner, balance)
            if nargin > 0
                obj.Owner = owner;
            end
            if nargin > 1
                obj.Balance = balance;
            end
        end
        function deposit(obj, x)
            obj.Balance = obj.Balance + x;
        end
        function withdraw(obj, x)
            obj.Balance = obj.Balance - x;
            if obj.Balance < 0
                notify(obj, 'Overdrawn');
            end
        end
        function v = get.Interest(obj)
            v = obj.Balance * Account.Rate;
        end
        function set.Owner(obj, name)
            obj.Owner = upper(name);
        end
        function n = count(obj)
            n = numel(obj.Owner);
        end
    end
    methods (Static)
        function a = joint(x, y)
            a = Account([x ' & ' y], 0);
        end
    end
end
""")
write('Vec.m', """classdef Vec
    % VEC  A value class with operators.
    properties
        X = 0
        Y = 0
    end
    methods
        function v = Vec(x, y)
            if nargin == 2
                v.X = x; v.Y = y;
            end
        end
        function r = plus(a, b)
            r = Vec(a.X + b.X, a.Y + b.Y);
        end
        function r = mtimes(k, v)
            r = Vec(k * v.X, k * v.Y);
        end
        function t = eq(a, b)
            t = a.X == b.X && a.Y == b.Y;
        end
        function r = uminus(v)
            r = Vec(-v.X, -v.Y);
        end
        function n = norm(v)
            n = sqrt(v.X^2 + v.Y^2);
        end
        function v = scale(v, k)
            v.X = k * v.X;
            v.Y = k * v.Y;
        end
        function disp(v)
            fprintf('(%g, %g)\\n', v.X, v.Y);
        end
    end
end
""")
write('Saving.m', """classdef Saving < Account
    properties
        Limit = 100
    end
    methods
        function obj = Saving(owner, limit)
            obj = obj@Account(owner, 10);
            obj.Limit = limit;
        end
        function withdraw(obj, x)
            if x > obj.Limit
                error('Saving:limit', 'Over the limit of %g.', obj.Limit);
            end
            withdraw@Account(obj, x);
        end
    end
end
""")

# ---- handle classes ---------------------------------------------------------------------------------------------------
W, _ = run("a = Account('ann', 100); deposit(a, 50); a.deposit(25); b = a; b.withdraw(10); x = a.Balance; o = a.Owner; i = a.Interest; r = Account.Rate; "
           "k = class(a); h = isa(a, 'handle'); n = a.count(); m = count(a); ob = isobject(a);")
same('a handle class: methods called both ways, a copy is the same object', (W['x'], val(W['o']), round(W['i'], 12), W['r'], val(W['k']), W['h'], W['n'], W['m'], W['ob']),
     (165.0, 'ANN', 3.3, 0.02, 'Account', True, 3.0, 3.0, True))
W, _ = run("a = Account; o = a.Owner; b = a.Balance; c = Account.joint('bo', 'cy'); co = c.Owner;")
same('defaults (set without the set method), a static method, the set method on an assignment', (val(W['o']), W['b'], val(W['co'])), ('nobody', 0.0, 'BO & CY'))
W, out = run("a = Account('x', 5); L = addlistener(a, 'Overdrawn', @(src, evt) fprintf('overdrawn %s %g\\n', evt.EventName, src.Balance)); a.withdraw(20);")
C('events: addlistener, notify, the listener with the source and event data', 'overdrawn Overdrawn -15' in out, out)
W, _ = run("a = Account('x', 5); delete(a); v = isvalid(a); try, a.Balance, e = ''; catch ex, e = ex.message; end")
same('delete and isvalid; a deleted object refuses', (W['v'], val(W['e'])), (False, 'Invalid or deleted object.'))
refused('an unknown property', "a = Account; a.Nope = 1", "Unrecognized property 'Nope'")
refused('a Constant property cannot be set', "a = Account; a.Rate = 1", 'Constant property')
W, _ = run("p = properties(Account('x')); m = methods(Account('x')); im = ismethod(Account('x'), 'deposit'); ip = isprop(Account('x'), 'Balance');")
same('properties, methods, ismethod, isprop', ([val(x) for x in W['p'].a.reshape(-1)], 'deposit' in [val(x) for x in W['m'].a.reshape(-1)], W['im'], W['ip']),
     (['Owner', 'Balance', 'Rate', 'Interest'], True, True, True))
W, out = run("a = Account('z', 1)")
C('a displayed object lists its properties', 'Account with properties:' in out and 'Balance: 1' in out, out)

# ---- value classes, operators and overloaded builtins --------------------------------------------------------------------
W, _ = run("v = Vec(1, 2); w = v; w.X = 10; a = v.X; b = w.X; u = v + Vec(3, 4); s = 2 * v; t = (v == Vec(1, 2)); n = -v; nn = norm(Vec(3, 4)); q = scale(v, 3); c = v.X; d = q.X; z = norm([3 4]);")
same('a value class: copies independent; plus, mtimes, eq, uminus; a method named as a builtin; the builtin itself', (W['a'], W['b'], W['u'].p['X'], W['u'].p['Y'], W['s'].p['Y'], W['t'], W['n'].p['X'], W['nn'], W['c'], W['d'], W['z']),
     (1.0, 10.0, 4.0, 6.0, 4.0, True, -1.0, 5.0, 1.0, 3.0, 5.0))
W, out = run("v = Vec(1, 2)")
C("display uses the class's disp", 'v =' in out and '(1, 2)' in out, out)
refused('an operator the class has not', "v = Vec(1, 2); v - v", "Operator '-' is not supported")

# ---- inheritance ----------------------------------------------------------------------------------------------------------
W, _ = run("s = Saving('dee', 50); s.withdraw(20); b = s.Balance; k = isa(s, 'Account'); l = s.Limit; o = s.Owner;")
same('a subclass: the superclass constructor called, a method calling the superclass method, isa', (W['b'], W['k'], W['l'], val(W['o'])), (-10.0, True, 50.0, 'DEE'))
refused('the subclass method refuses as it was written', "s = Saving('dee', 50); s.withdraw(60)", 'Over the limit of 50.')

# ---- app components -------------------------------------------------------------------------------------------------------------
W, _ = run("f = uifigure('Name', 'T'); b = uibutton(f); l = uilabel(f); e = uieditfield(f, 'numeric'); d = uidropdown(f); s = uislider(f); k = uiknob(f, 'discrete'); "
           "g = uigauge(f, 'semicircular'); w = uiswitch(f, 'toggle'); c = uicheckbox(f); "
           "t = {class(b), b.Type, class(e), e.Type, class(d), class(k), k.Type, g.Style, w.Orientation, class(f)}; hv = f.HandleVisibility; gf = isempty(get(0, 'CurrentFigure')) || get(0, 'CurrentFigure') ~= f;")
same('components: their classes and Types; a uifigure hides its handle', ([val(x) for x in W['t'].a.reshape(-1)], val(W['hv']), W['gf']),
     (['matlab.ui.control.Button', 'uibutton', 'matlab.ui.control.NumericEditField', 'uinumericeditfield', 'matlab.ui.control.DropDown',
       'matlab.ui.control.DiscreteKnob', 'uidiscreteknob', 'semicircular', 'vertical', 'matlab.ui.Figure'], 'off', True))
W, _ = run("f = uifigure; e = uieditfield(f, 'numeric', 'Limits', [0 10], 'Value', 3); d = uidropdown(f, 'Items', {'a', 'b'}, 'ItemsData', [10 20]); v = d.Value; "
           "l = uilistbox(f, 'Items', {'p', 'q', 'r'}, 'Multiselect', 'on', 'Value', {'p', 'r'}); lv = l.Value; s = uislider(f, 'Limits', [1 5]); sv = s.Value; ta = uitextarea(f, 'Value', 'one'); tv = ta.Value;")
same("values: within Limits, from ItemsData, several in a list box, a slider brought into new Limits, a text area's cell",
     (W['e'].props['Value'], W['v'], [val(x) for x in W['lv'].a.reshape(-1)], W['sv'], [val(x) for x in W['tv'].a.reshape(-1)]), (3.0, 10.0, ['p', 'r'], 1.0, ['one']))
refused('a numeric field outside its Limits', "f = uifigure; e = uieditfield(f, 'numeric', 'Limits', [0 10]); e.Value = 11", "within the Limits")
refused("a drop-down's Value not among its Items", "f = uifigure; d = uidropdown(f); d.Value = 'zz'", "element of 'Items'")
refused('a radio button outside a button group', "f = uifigure; uiradiobutton(f)", 'button group')
W, _ = run("f = uifigure; bg = uibuttongroup(f); r1 = uiradiobutton(bg, 'Text', 'A'); r2 = uiradiobutton(bg, 'Text', 'B'); a = r1.Value; r2.Value = true; b = r1.Value; s = bg.SelectedObject.Text; u = bg.Units;")
same('radio buttons in a group: the first chosen, choosing one clears the other; a group in an app takes pixels', (W['a'], W['b'], val(W['s']), val(W['u'])), (True, False, 'B', 'pixels'))

# ---- events from the page ---------------------------------------------------------------------------------------------------
write('appendlog.m', "function appendlog(s)\nglobal log_\nlog_{end+1} = s;\nend\n")
W, _ = run("global log_; log_ = {}; f = uifigure; b = uibutton(f, 'ButtonPushedFcn', @(s, e) appendlog(e.EventName)); "
           "s = uislider(f, 'ValueChangedFcn', @(s, e) appendlog(sprintf('%g<-%g', e.Value, e.PreviousValue)), 'ValueChangingFcn', @(s, e) appendlog(sprintf('~%g', e.Value)));"
           "d = uidropdown(f, 'Items', {'x', 'y'}, 'ValueChangedFcn', @(s, e) appendlog(e.Value)); e = uieditfield(f, 'numeric', 'Limits', [0 5]);")
f, b, s, d, e = (W[k] for k in ('f', 'b', 's', 'd', 'e'))
E._control(b, f, {'action': 'push'})
E._control(s, f, {'action': 'changing', 'value': 30.0})
E._control(s, f, {'action': 'value', 'value': 40.0})
E._control(d, f, {'action': 'value', 'value': 1})
E._control(e, f, {'action': 'value', 'value': 9.0})
asyncio.run(E.process(False))
log = [val(x) for x in R.GLOBALS['log_'].a.reshape(-1)]
same('the page reports: a push, a slider dragged and let go, a drop-down chosen; callbacks with their event data', log, ['ButtonPushed', '~30', '40<-0', 'y'])
same('a value outside the Limits typed into a numeric field is not taken', e.props['Value'], 0.0)

# ---- grid layouts ---------------------------------------------------------------------------------------------------------
W, _ = run("f = uifigure('Position', [100 100 400 300]); g = uigridlayout(f, [2 2]); g.RowHeight = {30, '1x'}; g.ColumnWidth = {100, '2x'}; "
           "a = uibutton(g); b = uilabel(g); c = uiaxes(g); c.Layout.Row = 2; c.Layout.Column = [1 2]; pa = a.Position; pb = b.Position;")
same('a grid places its children: fixed and weighted rows and columns, padding and spacing', (W['pa'].tolist(), W['pb'].tolist()), ([[10.0, 260.0, 100.0, 30.0]], [[120.0, 260.0, 270.0, 30.0]]))
d = serialize_figure(W['f'])
grid = d['controls'][0]
same('the page is told: the grid with its children; the axes spanning both columns placed in it', (grid['type'], len(grid['children']), d['axes'][0]['parent'] == W['g'].id,
                                                                                                   [round(x) for x in d['axes'][0]['position']]),
     ('uigridlayout', 2, True, [55, 48, 320, 174]))

# ---- an app as App Designer writes them --------------------------------------------------------------------------------------
write('TinyApp.m', """classdef TinyApp < matlab.apps.AppBase

    % Properties that correspond to app components
    properties (Access = public)
        UIFigure  matlab.ui.Figure
        Field     matlab.ui.control.NumericEditField
        Button    matlab.ui.control.Button
    end

    properties (Access = private)
        Started = false
    end

    methods (Access = private)
        function startupFcn(app)
            app.Started = true;
        end

        function ButtonPushed(app, event)
            app.Field.Value = app.Field.Value + 1;
        end
    end

    methods (Access = private)
        function createComponents(app)
            app.UIFigure = uifigure('Visible', 'off');
            app.UIFigure.Position = [100 100 300 200];
            app.UIFigure.Name = 'Tiny';
            app.Field = uieditfield(app.UIFigure, 'numeric');
            app.Field.Position = [20 150 100 22];
            app.Button = uibutton(app.UIFigure, 'push');
            app.Button.ButtonPushedFcn = createCallbackFcn(app, @ButtonPushed, true);
            app.Button.Position = [20 110 100 22];
            app.Button.Text = 'Add one';
            app.UIFigure.Visible = 'on';
        end
    end

    methods (Access = public)
        function app = TinyApp
            createComponents(app)
            registerApp(app, app.UIFigure)
            runStartupFcn(app, @startupFcn)
            if nargout == 0
                clear app
            end
        end

        function delete(app)
            delete(app.UIFigure)
        end
    end
end
""")
W, out = run("close all force; app = TinyApp; st = app.Started; fig = app.UIFigure; nm = fig.Name;")
app, fig = W['app'], W['fig']
same('an App Designer app: made, its startup function run', (W['st'], val(W['nm']), app.cls), (True, 'Tiny', 'TinyApp'))
for _ in range(2):
    E._control(app.getprop('Button'), fig, {'action': 'push'})
asyncio.run(E.process(False))
same('its button calls the method with the app (createCallbackFcn)', app.getprop('Field').props['Value'], 2.0)
W, out = run("TinyApp")
C('run at the prompt, the app gives no ans (its constructor clears it)', 'ans' not in out and 'ans' not in W, out)
W, _ = run("close all force; app = TinyApp; f = app.UIFigure; delete(f); v = isvalid(app);")
same('closing its window deletes the app (registerApp)', W['v'], False)
W, _ = run("close all force; app = TinyApp; f = app.UIFigure; delete(app); v = isvalid(f);")
same('deleting the app closes its window', W['v'], False)
W, _ = run("a = Account('q', 1); b = Account('q', 1);")
W, out = run("Account('r', 2)")
C('a constructor at the prompt gives ans', 'ans =' in out and 'Account with properties' in out, out)

# ---- set methods of value classes, property validation ----------------------------------------------------------
write('Doubler.m', """classdef Doubler
    properties
        s = 1
    end
    methods
        function o = set.s(o, v)
            o.s = v * 2;
        end
    end
end
""")
W, out = run("d = Doubler; d.s = 5; v = d.s;")
same("a value class's set method sets its own property (not itself again)", (val(W['v']), 'recursion' in out), (10.0, False))
write('Checked.m', """classdef Checked
    properties
        a (1,1) double {mustBePositive} = 1
        b (1,:) char = 'x'
        c {mustBeMember(c, {'u', 'v'})} = 'u'
        d (2,2) = zeros(2)
    end
end
""")
refused('a property validator is run when it is set', "k = Checked; k.a = -2", "Error setting property 'a' of class 'Checked'. Value must be positive.")
refused("a property's size is checked", "k = Checked; k.a = [1 2]", 'Value must be of size 1x1.')
refused('a validator written as a call is run as written', "k = Checked; k.c = 'w'", 'Value must be a member of this set')
W, _ = run("k = Checked; k.b = \"str\"; cb = class(k.b); k.d = 5; d = k.d;")
same('a value is converted to the class and a scalar spread to the size', (val(W['cb']), val(W['d'])), ('char', [[5.0, 5.0], [5.0, 5.0]]))

# ---- arguments blocks ---------------------------------------------------------------------------------------------
write('argsv.m', """function y = argsv(x, n, opts)
  arguments
    x (1,:) double {mustBePositive}
    n (1,1) {mustBeInteger, mustBeLessThan(n, 10)} = 2
    opts.Scale (1,1) double {mustBePositive} = 1  % a comment
    opts.Label string = "none"
  end
  y = x * n * opts.Scale;
  if opts.Label ~= "none", y = -y; end
end
""")
W, _ = run("a = argsv([1 2]); b = argsv([1; 2], 3); c = argsv(5, 2, Scale=10); d = argsv(5, 2, 'scale', 3, 'Label', 'L'); e = argsv(1, 2, 'Sc', 2);")
same('arguments: defaults, a column turned to the row asked for, name=value and name, value pairs (any case, a unique start)',
     [val(W[k]) for k in 'abcde'], [[[2.0, 4.0]], [[3.0, 6.0]], 100.0, -30.0, 4.0])
refused('arguments: a validator named alone takes the value', 'argsv([1 -2])', 'Invalid argument at position 1. Value must be positive.')
refused('arguments: a validator written as a call', 'argsv(1, 20)', 'Invalid argument at position 2. Value must be less than 10.')
refused("arguments: a name-value argument's validator", 'argsv(1, 2, Scale=-1)', "Invalid value for 'Scale' argument. Value must be positive.")
refused('arguments: an unknown name is named, with the names there are', 'argsv(1, 2, Bogus=1)', "'Bogus' is not a name-value argument of argsv. Its names: Scale, Label.")
refused('arguments: a name without its value', "argsv(1, 2, 'Scale')", 'must come in pairs')
refused("arguments: a value of the wrong size", 'argsv(ones(2))', 'Invalid argument at position 1. Value must be of size 1x:.')

# ---- enumerations ---------------------------------------------------------------------------------------------------
write('Wk.m', """classdef Wk
    enumeration
        Mon, Tue, Wed
    end
    methods
        function tf = isStart(o)
            tf = o == Wk.Mon;
        end
    end
end
""")
write('Lvl.m', """classdef Lvl < uint8
    enumeration
        Low (1), High (2)
    end
end
""")
write('Dy.m', """classdef Dy
    properties
        n
    end
    enumeration
        Mon (1), Tue (2)
    end
    methods
        function o = Dy(k), o.n = k; end
    end
end
""")
W, out = run("w = Wk.Tue")
C('an enumeration member shows as its class and name', 'Wk enumeration' in out and out.rstrip().endswith('Tue'), out)
W, out = run("a = Wk.Mon == Wk.Mon; b = Wk.Mon == Wk.Tue; c = Wk.Tue == 'Tue'; x = [Wk.Mon Wk.Tue Wk.Wed]; d = x == Wk.Tue; "
             "e = isStart(Wk.Mon); f = Wk.Tue.isStart(); g = char(Wk.Wed); [tf, loc] = ismember([Wk.Wed Wk.Mon], [Wk.Mon Wk.Tue]); "
             "switch Wk.Tue, case Wk.Mon, s = 1; case Wk.Tue, s = 2; end; cl = class(Wk.Mon);")
same('enumeration members compare by member (and by name), in arrays too; methods, char, ismember and switch take them',
     [val(W[k]) for k in ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'tf', 'loc', 's', 'cl')],
     [True, False, True, [[False, True, False]], True, False, 'Wed', [[False, True]], [[0.0, 1.0]], 2.0, 'Wk'])
W, _ = run("a = uint8(Lvl.High); b = Lvl.High > Lvl.Low; c = Lvl.High + 1; cc = class(c); d = Dy.Tue.n; [m, nm] = enumeration('Wk'); k = numel(m);")
same('an enumeration based on uint8 is those numbers; members made by the constructor; enumeration lists them',
     [val(W[k]) for k in ('a', 'b', 'c', 'cc', 'd', 'k')] + [[x.str() for x in W['nm'].a.reshape(-1)]], [2, True, 3, 'uint8', 2.0, 3.0, ['Mon', 'Tue', 'Wed']])
W, out = run("x = [Wk.Mon Wk.Wed]")
C('an array of members shows their names', '1×2 Wk enumeration array' in out and 'Mon    Wed' in out, out)

# ---- packages and import --------------------------------------------------------------------------------------------
os.makedirs(os.path.join(TMP, '+pkg', '+sub'), exist_ok=True)
os.makedirs(os.path.join(TMP, '+pkg', '@Box'), exist_ok=True)
write('+pkg/f.m', "function y = f(x)\n y = x + 1;\nend\n")
write('+pkg/+sub/g.m', "function y = g(x)\n y = 10 * pkg.f(x);\nend\n")
write('+pkg/Pt.m', "classdef Pt\n  properties\n    x = 0\n  end\n  methods\n    function o = Pt(x), o.x = x; end\n  end\n  methods (Static)\n    function o = origin(), o = pkg.Pt(0); end\n  end\nend\n")
write('+pkg/@Box/Box.m', "classdef Box\n  properties\n    w = 1\n  end\nend\n")
write('usesimport.m', "function y = usesimport(x)\n  import pkg.*\n  y = f(x) + Pt(5).x;\nend\n")
W, _ = run("a = pkg.f(1); b = pkg.sub.g(1); p = pkg.Pt(3); c = p.x; cl = class(p); o = pkg.Pt.origin(); d = o.x; q = pkg.Box; e = q.w; f2 = usesimport(1);")
same('packages: functions in +pkg folders, nested packages, a class (and its static method) by its full name, an @-folder class, import in a function',
     [val(W[k]) for k in ('a', 'b', 'c', 'cl', 'd', 'e', 'f2')], [2.0, 20.0, 3.0, 'pkg.Pt', 0.0, 1.0, 7.0])
W, _ = run("import pkg.sub.g; a = g(2); il = import;")
same('import of one name, and import listing what is imported', (val(W['a']), [x.str() for x in W['il'].a.reshape(-1)]), (30.0, ['pkg.sub.g']))
refused('import refuses what is no package name', 'import bad', "'bad' is not a name to import")

# ---- the Editor's check of a class file ---------------------------------------------------------------------------
# ---- a value subclass's bare superclass constructor call; isobject, ismethod and methods of built-in classes ------------------------
write('VAnimal.m', "classdef VAnimal\n    properties\n        Name\n    end\n    methods\n        function a = VAnimal(name)\n            a.Name = name;\n        end\n"
      "        function s = describe(a)\n            s = ['animal ' a.Name];\n        end\n    end\nend\n")
write('VDog.m', "classdef VDog < VAnimal\n    properties\n        Breed\n    end\n    methods\n        function d = VDog(name, breed)\n            d@VAnimal(name);\n"
      "            d.Breed = breed;\n        end\n        function s = describe(d)\n            s = [describe@VAnimal(d) ', ' d.Breed];\n        end\n    end\nend\n")
W, _ = run("d = VDog('Rex', 'collie'); nm = d.Name; ds = describe(d);")
same("obj@Super(args); alone in a value class's constructor makes the object (as obj = obj@Super(args))", (val(W['nm']), val(W['ds'])), ('Rex', 'animal Rex, collie'))
W, _ = run("k = containers.Map({'a'}, {1}); e = MException('my:id', 'text'); o1 = [isobject(k) isobject(e) isobject(datetime(2026, 1, 1))]; "
           "o2 = [isobject(5) isobject('t') isobject(struct('a', 1)) isobject({1}) isobject(@sin) isobject(int8(1)) isobject(true)]; "
           "m1 = [ismethod(k, 'keys') ismethod(k, 'sort') ismethod(e, 'getReport') ismethod(e, 'keys')]; mk = methods(k);")
same('isobject: true for objects of classes (a map, an exception, a datetime), false for the fundamental types',
     (val(W['o1']), val(W['o2'])), ([[True, True, True]], [[False] * 7]))
same("ismethod and methods know a map's and an exception's methods",
     (val(W['m1']), [val(x) for x in W['mk'].a.reshape(-1)]), ([[True, False, True, False]], ['isKey', 'keys', 'length', 'remove', 'size', 'values']))

from plab import worker_api as API  # noqa: E402
GOOD = "classdef T < handle\n    properties\n        a = 1\n    end\n    methods\n        function obj = T(x)\n            obj.a = x;\n        end\n        function r = twice(obj)\n            r = 2 * obj.a;\n        end\n    end\nend\n"
same("the Editor's check finds nothing wrong with a class", json.loads(API.lint(GOOD)), [])
same('and a mistake in a method is reported at its own line', [m['line'] for m in json.loads(API.lint(GOOD.replace('r = 2 * obj.a;', 'r = 2 * (obj.a;')))], [10])

sys.exit(C.done())
