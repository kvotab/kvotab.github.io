"""User interfaces, run natively (CPython with numpy and scipy): the
controls, panels, tables, tabs, menus and toolbars and their properties;
what people do with them (the page's events, as uievents.handle takes
them) and the callbacks that answer, by text, function handle and cell;
gcbo, gcbf and gco; uiwait, waitfor, drawnow and pause letting callbacks
run; the dialogs (the page's answers stood in for); timers; data kept with
objects; textread and strmatch; and the description the page builds from.

    python3 test_gui.py          (from any folder; needs numpy and scipy)
"""
import asyncio
import base64
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab import uievents as E  # noqa: E402
from plab import worker_api as W  # noqa: E402
from plab.graphics_base import STORE, serialize_figure  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-gui-')
R.STATE['cwd'] = TMP
R.STATE['home'] = TMP
EVENTS = []          # what the engine told the page
ASKED = []           # what it asked the page
ANSWERS = {}         # the page's answers, by request type
R.EVENT_HOOK[0] = EVENTS.append


async def _page(req):
    ASKED.append(req)
    a = ANSWERS.get(req['type'])
    return a(req) if callable(a) else a


R.PAGE_HOOK[0] = _page


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, got, want=True):
        self.n += 1
        ok = got == want
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}: got {got!r}, want {want!r}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


check = Checks()


def run(code):
    """Run code in the base workspace; the output."""
    R.take_output()
    asyncio.run(R.execute(code))
    return R.take_output()


def val(name):
    return R.BASE[name]


def num(code):
    """The value of an expression, as a Python number or list."""
    run(f'plabTestValue = {code};')
    v = R.BASE.pop('plabTestValue')
    a = np.asarray(v.a if hasattr(v, 'a') and not isinstance(v, np.ndarray) else v)
    if a.dtype.kind in 'U':
        return str(a)
    return a.reshape(-1).tolist() if a.size != 1 else a.reshape(-1)[0].item()


def text(code):
    run(f"plabTestValue = {code};")
    from plab.values import py_str
    return py_str(R.BASE.pop('plabTestValue'))


def ui(ev):
    """The page reports an event; the callbacks it queued run."""
    n = json.loads(W.ui_event(json.dumps(ev)))['queued']
    R.take_output()
    asyncio.run(E.run_queued())
    return n, R.take_output()


def idof(name):
    return val(name).id


# ---- objects and their properties ----------------------------------------------------------------------
out = run("f = figure('Name', 'Test', 'Position', [100 100 400 300]); b = uicontrol('String', 'Go');")
check('making a control prints nothing', out, '')
check('a uicontrol is a pushbutton by default', text("get(b, 'Style')"), 'pushbutton')
check('in pixels by default', text("get(b, 'Units')"), 'pixels')
check('its default place', num("get(b, 'Position')"), [20.0, 20.0, 60.0, 20.0])
check('its parent is the current figure', num("get(b, 'Parent') == f"), True)
check('its type', text("get(b, 'Type')"), 'uicontrol')
check('the style is checked', 'is not a valid value for Style' in run("set(b, 'Style', 'knob')"), True)
check('an unknown property is refused', "Unrecognized property 'Colour'" in run("set(b, 'Colour', 'r')"), True)
run("set(b, 'Units', 'normalized');")
check('Units change keeps the place', num("round(get(b, 'Position') * 1000) / 1000"), [0.05, 0.067, 0.15, 0.067])
run("set(b, 'Units', 'pixels');")
check('and back again', num("round(get(b, 'Position'))"), [20.0, 20.0, 60.0, 20.0])
run("set(b, 'Tooltip', 'Press it'); m = uimenu(f, 'Text', 'File', 'MenuSelectedFcn', 'x = 1;');")
check('Tooltip is TooltipString', text("get(b, 'TooltipString')"), 'Press it')
check('Text is a menu Label', text("get(m, 'Label')"), 'File')
check('MenuSelectedFcn is its Callback', text("get(m, 'Callback')"), 'x = 1;')
run("m2 = uimenu(f, 'Label', 'Edit'); m3 = uimenu(f, 'Label', 'View');")
check('menus are placed in order', num("[get(m, 'Position') get(m2, 'Position') get(m3, 'Position')]"), [1.0, 2.0, 3.0])
run("set(m3, 'Position', 1);")
check('Position moves a menu', num("[get(m3, 'Position') get(m, 'Position') get(m2, 'Position')]"), [1.0, 2.0, 3.0])
run("a1 = uimenu(m, 'Label', 'Open', 'Accelerator', 'Ox');")
check('an Accelerator is one key', text("get(a1, 'Accelerator')"), 'O')
check('on/off properties read as text', text("get(a1, 'Checked')"), 'off')
run("set(a1, 'Checked', 'on', 'Enable', 'off');")
check('and are set as text', text("[get(a1, 'Checked') get(a1, 'Enable')]"), 'onoff')
run("g = uibuttongroup(f); r1 = uicontrol(g, 'Style', 'radiobutton', 'String', 'A'); r2 = uicontrol(g, 'Style', 'radiobutton', 'String', 'B');")
check('the first radio button of a group is chosen', num("[get(r1, 'Value') get(r2, 'Value')]"), [1.0, 0.0])
check('SelectedObject', num("get(g, 'SelectedObject') == r1"), True)
run("set(g, 'SelectedObject', r2);")
check('setting SelectedObject chooses', num("[get(r1, 'Value') get(r2, 'Value')]"), [0.0, 1.0])
run("tg = uitabgroup(f); t1 = uitab(tg, 'Title', 'One'); t2 = uitab(tg, 'Title', 'Two');")
check('the first tab is shown', num("get(tg, 'SelectedTab') == t1"), True)
run("tb = uitable(f, 'Data', magic(3), 'ColumnName', {'a', 'b', 'c'});")
check('a table keeps its data', num("get(tb, 'Data')"), [8.0, 1.0, 6.0, 3.0, 5.0, 7.0, 4.0, 9.0, 2.0])
check('RowName is numbered', text("get(tb, 'RowName')"), 'numbered')
check('findobj finds controls by Type', num("numel(findobj(f, 'Type', 'uicontrol'))"), 3)
check('and menus', num("numel(findobj(f, 'Type', 'uimenu'))"), 4)
check('handles compare', num("[b == b, b == r1, b ~= r1]"), [True, False, True])
check('a handle against its number', num("f == double(f)"), True)
run("p = uipanel(f, 'Title', 'Panel', 'Position', [0.5 0.5 0.5 0.5]); ax = axes('Parent', p); cm = uicontextmenu(f); set(ax, 'UIContextMenu', cm);")
check('axes in a panel', num("get(ax, 'Parent') == p"), True)
check('ContextMenu is UIContextMenu', num("get(ax, 'ContextMenu') == cm"), True)
check('a panel is in normalized units', text("get(p, 'Units')"), 'normalized')

# ---- what the page is given ------------------------------------------------------------------------------------
run("tbar = uitoolbar(f); tool = uitoggletool(tbar, 'CData', rand(16, 16, 3), 'TooltipString', 'T', 'Separator', 'on');")
d = serialize_figure(val('f'))
json.dumps(d)
check('the description is JSON', True)
check('menus in order, with their items', [m['label'] for m in d['menus']], ['View', 'File', 'Edit'])
check('a menu item and its accelerator', d['menus'][1]['items'][0]['accel'], 'O')
check('toolbars and their tools', [(t['kind'], t['tip'], t['sep'], t['state']) for t in d['toolbars'][0]['tools']], [('toggle', 'T', True, False)])
check('a tool picture as RGBA bytes', (d['toolbars'][0]['tools'][0]['cdata']['w'], len(d['toolbars'][0]['tools'][0]['cdata']['rgba']) > 1000), (16, True))
check('controls, and what panels hold', [c['type'] for c in d['controls']], ['uicontrol', 'uibuttongroup', 'uitabgroup', 'uitable', 'uipanel'])
check('the radio buttons in the group', [c['string'] for c in d['controls'][1]['children']], [['A'], ['B']])
check('axes in a panel are drawn too, in it', [a['parent'] == val('p').id for a in d['axes']], [True])
check('and their context menu', d['axes'][0]['cmenu'], val('cm').id)
check('the close button closes', d['closeDefault'], True)
check('no callbacks to hear', d['flags']['kpf'] or d['flags']['wbdf'], False)
run("set(f, 'KeyPressFcn', 'k = 1;', 'CloseRequestFcn', 'disp(1)');")
d = serialize_figure(val('f'))
check('a KeyPressFcn wants keys', d['flags']['kpf'], True)
check('a CloseRequestFcn of its own decides', d['closeDefault'], False)
run("axt = axes('Parent', t2);")
check('only the shown tab\'s axes are drawn', len(serialize_figure(val('f'))['axes']), 1)
run("set(tg, 'SelectedTab', t2);")
check('the other tab\'s, when it is shown', len(serialize_figure(val('f'))['axes']), 2)
run("close all force")

# ---- callbacks ---------------------------------------------------------------------------------------------------
run("f = figure; b = uicontrol('Callback', 'clicks = clicks + 1;'); clicks = 0;")
n, out = ui({'type': 'control', 'id': idof('b'), 'action': 'click'})
check('a click queues the Callback', n, 1)
check('a text callback runs in the base workspace', num('clicks'), 1)
run("b2 = uicontrol('Callback', @(src, ev) assignin('base', 'got', {get(src, 'Style'), ev.EventName}));")
ui({'type': 'control', 'id': idof('b2'), 'action': 'click'})
check('a handle gets the object and the event data', [str(x) if not hasattr(x, 'a') else ''.join(map(chr, x.a.reshape(-1).astype(int))) for x in val('got').items()], ['pushbutton', 'Action'])
run("b3 = uicontrol('Callback', {@(src, ev, a, b) assignin('base', 'sum3', a + b), 2, 5});")
ui({'type': 'control', 'id': idof('b3'), 'action': 'click'})
check('a cell callback gets its extra inputs', num('sum3'), 7)
run("b4 = uicontrol('Callback', 'who_ = gcbo; fig_ = gcbf; [o_, f_] = gcbo;');")
ui({'type': 'control', 'id': idof('b4'), 'action': 'click'})
check('gcbo and gcbf in a callback', num('[who_ == b4, fig_ == f, o_ == b4, f_ == f]'), [True, True, True, True])
check('gcbo is empty outside', num('isempty(gcbo) && isempty(gcbf)'), True)
run("b5 = uicontrol('Callback', 'error(''my:id'', ''It broke.'')');")
n, out = ui({'type': 'control', 'id': idof('b5'), 'action': 'click'})
check('an error in a callback is shown', 'It broke.' in out and 'Error while evaluating UIControl Callback.' in out, True)
check('and what runs goes on', num('clicks'), 1)
run("c = uicontrol('Style', 'checkbox', 'Callback', 'cv = get(gcbo, ''Value'');');")
ui({'type': 'control', 'id': idof('c'), 'action': 'toggle', 'on': True})
check('a check box sets Value to Max', num('cv'), 1)
ui({'type': 'control', 'id': idof('c'), 'action': 'toggle', 'on': False})
check('and to Min', num('cv'), 0)
run("e = uicontrol('Style', 'edit', 'String', 'old', 'Callback', 'es = get(gcbo, ''String'');');")
ui({'type': 'control', 'id': idof('e'), 'action': 'edit', 'string': 'new text'})
check('an edit field sets String', text('es'), 'new text')
run("e2 = uicontrol('Style', 'edit', 'Max', 2, 'Callback', 'es2 = get(gcbo, ''String'');');")
ui({'type': 'control', 'id': idof('e2'), 'action': 'edit', 'string': ['one', 'two']})
check('lines typed in a multi-line field', num('numel(es2)'), 2)
run("s = uicontrol('Style', 'slider', 'Min', 0, 'Max', 10, 'Callback', 'sv = get(gcbo, ''Value'');');")
ui({'type': 'control', 'id': idof('s'), 'action': 'slider', 'value': 12})
check('a slider keeps Value within Min and Max', num('sv'), 10)
run("lb = uicontrol('Style', 'listbox', 'String', {'a', 'b', 'c'}, 'Max', 2, 'Callback', 'lv = get(gcbo, ''Value''); st = get(gcbf, ''SelectionType'');');")
ui({'type': 'control', 'id': idof('lb'), 'action': 'list', 'value': [1, 3]})
check('a list sets the chosen items', num('lv'), [1.0, 3.0])
ui({'type': 'control', 'id': idof('lb'), 'action': 'list', 'value': [2], 'open': True})
check('a double click is SelectionType open', text('st'), 'open')
run("pm = uicontrol('Style', 'popupmenu', 'String', 'x|y|z', 'Callback', 'pv = get(gcbo, ''Value'');');")
ui({'type': 'control', 'id': idof('pm'), 'action': 'popup', 'value': [3]})
check('a popup menu sets Value', num('pv'), 3)
check('and its items may be given with |', serialize_figure(val('f'))['controls'][-1]['string'], ['x', 'y', 'z'])
run("g = uibuttongroup; ra = uicontrol(g, 'Style', 'radiobutton', 'String', 'A'); rb = uicontrol(g, 'Style', 'radiobutton', 'String', 'B');")
run("set(g, 'SelectionChangedFcn', @(src, ev) assignin('base', 'change', {get(ev.OldValue, 'String'), get(ev.NewValue, 'String'), ev.EventName}));")
ui({'type': 'control', 'id': idof('rb'), 'action': 'radio'})
check('a radio button in a group: SelectionChangedFcn', [x.str() for x in val('change').items()], ['A', 'B', 'SelectionChanged'])
check('and the buttons follow', num("[get(ra, 'Value') get(rb, 'Value')]"), [0.0, 1.0])
run("t = uitable('Data', [1 2; 3 4], 'ColumnEditable', [false true], 'CellEditCallback', @(src, ev) assignin('base', 'edit_', {ev.Indices, ev.PreviousData, ev.NewData}));")
ui({'type': 'control', 'id': idof('t'), 'action': 'edit', 'row': 2, 'col': 2, 'text': '40'})
check('a table edit sets Data', num("get(t, 'Data')"), [1.0, 2.0, 3.0, 40.0])
check('and tells where, what was and what is', [np.asarray(x).reshape(-1).tolist() for x in val('edit_').items()], [[2.0, 2.0], [4.0], [40.0]])
run("tg = uitabgroup('SelectionChangedFcn', 'tabs_ = get(get(gcbo, ''SelectedTab''), ''Title'');'); ta = uitab(tg, 'Title', 'A'); tb_ = uitab(tg, 'Title', 'B');")
ui({'type': 'control', 'id': idof('tg'), 'action': 'tab', 'tab': idof('tb_')})
check('a tab chosen: SelectedTab and SelectionChangedFcn', text('tabs_'), 'B')
run("close all force")

# ---- menus, toolbars, keys, the mouse ---------------------------------------------------------------------------------
run("f = figure('MenuBar', 'none'); m = uimenu(f, 'Label', 'File', 'Callback', 'opened = 1;'); i1 = uimenu(m, 'Label', 'Go', 'Callback', 'went = 1;'); opened = 0; went = 0;")
ui({'type': 'menuopen', 'id': idof('m')})
check('a menu with a Callback runs it as it opens', num('opened'), 1)
ui({'type': 'menu', 'id': idof('i1')})
check('an item chosen runs its Callback', num('went'), 1)
run("cm = uicontextmenu(f, 'Callback', 'cmo = 1;'); ci = uimenu(cm, 'Label', 'Here', 'Callback', 'cmi = 1;');")
ui({'type': 'menuopen', 'id': idof('cm')})
ui({'type': 'menu', 'id': idof('ci')})
check('a context menu opening and its item', num('[cmo cmi]'), [1.0, 1.0])
run("tbar = uitoolbar(f); tt = uitoggletool(tbar, 'OnCallback', 'order = [order 1];', 'OffCallback', 'order = [order 2];', 'ClickedCallback', 'order = [order 3];'); order = [];")
ui({'type': 'tool', 'id': idof('tt')})
check('a toggle tool: State on, OnCallback, then ClickedCallback', (text("get(tt, 'State')"), num('order')), ('on', [1.0, 3.0]))
ui({'type': 'tool', 'id': idof('tt')})
check('and off again', (text("get(tt, 'State')"), num('order')), ('off', [1.0, 3.0, 2.0, 3.0]))
run("pt = uipushtool(tbar, 'ClickedCallback', 'pushed = 1;'); pushed = 0;")
ui({'type': 'tool', 'id': idof('pt')})
check('a push tool', num('pushed'), 1)
run("set(f, 'WindowKeyPressFcn', 'seq = [seq 1];', 'KeyPressFcn', @(src, ev) assignin('base', 'key_', {ev.Key, ev.Character, ev.Modifier, double(get(src, 'CurrentCharacter'))})); seq = [];")
ui({'type': 'key', 'id': idof('f'), 'key': 'leftarrow', 'character': '\x1c', 'modifiers': ['shift']})
k = val('key_').items()
check('a key: Key, Character, Modifier, CurrentCharacter', (k[0].str(), k[1].str(), [x.str() for x in k[2].items()], float(np.asarray(k[3]).reshape(-1)[0])),
      ('leftarrow', '\x1c', ['shift'], 28.0))
check('WindowKeyPressFcn first', num('seq'), 1)
run("ed = uicontrol('Style', 'edit', 'KeyPressFcn', 'edkey = 1;'); edkey = 0; key_ = 0;")
ui({'type': 'key', 'id': idof('ed'), 'key': 'a', 'character': 'a', 'modifiers': []})
check('a key typed in a field goes to the field', (num('edkey'), num('key_')), (1, 0))
run("ax = axes('Parent', f, 'ButtonDownFcn', 'axhit = 1;'); axis([0 10 0 10]); hold on; ln = plot([1 9], [5 5], 'ButtonDownFcn', 'lnhit = 1;'); tx = text(2, 2, 'T', 'HitTest', 'off'); axhit = 0; lnhit = 0;")
run("set(f, 'WindowButtonDownFcn', 'order2 = [order2 1];'); order2 = [];")
ui({'type': 'down', 'id': idof('f'), 'hit': idof('ln'), 'axes': idof('ax'), 'point': [3.0, 5.0], 'fpt': [120, 80], 'button': 1})
check('a click on a line: its ButtonDownFcn, after WindowButtonDownFcn', (num('lnhit'), num('axhit'), num('order2')), (1, 0, 1))
check('CurrentPoint of the axes: front and back of the point', num("get(ax, 'CurrentPoint')"), [3.0, 5.0, 1.0, 3.0, 5.0, 0.0])
check('CurrentPoint of the figure', num("get(f, 'CurrentPoint')"), [120.0, 80.0])
check('gco is what was clicked', num('gco == ln'), True)
ui({'type': 'down', 'id': idof('f'), 'hit': idof('tx'), 'axes': idof('ax'), 'point': [2.0, 2.0], 'fpt': [60, 60], 'button': 3})
check('HitTest off passes a click to the axes', num('axhit'), 1)
check('a right click is SelectionType alt', text("get(f, 'SelectionType')"), 'alt')
ui({'type': 'down', 'id': idof('f'), 'hit': idof('ax'), 'axes': idof('ax'), 'point': [2.0, 2.0], 'fpt': [60, 60], 'button': 1, 'clicks': 2})
check('a double click is open', text("get(f, 'SelectionType')"), 'open')
run("set(f, 'WindowButtonMotionFcn', 'moves = moves + 1;', 'WindowButtonUpFcn', 'ups = 1;'); moves = 0; ups = 0;")
for _ in range(3):
    W.ui_event(json.dumps({'type': 'motion', 'id': idof('f'), 'fpt': [10, 10]}))
asyncio.run(E.run_queued())
check('moves that came while one waited run once', num('moves'), 1)
ui({'type': 'up', 'id': idof('f'), 'fpt': [10, 10]})
check('WindowButtonUpFcn', num('ups'), 1)
run("set(f, 'WindowScrollWheelFcn', @(src, ev) assignin('base', 'wheel', ev.VerticalScrollCount));")
ui({'type': 'scroll', 'id': idof('f'), 'count': -1})
check('WindowScrollWheelFcn', num('wheel'), -1)
run("set(f, 'SizeChangedFcn', 'sized = get(gcbf, ''Position'');');")
ui({'type': 'resize', 'id': idof('f'), 'width': 500, 'height': 350})
check('a resize sets Position and runs SizeChangedFcn', num('sized(3:4)'), [500.0, 350.0])


def shown():
    """The page is sent the figures (as at a command's end); the callbacks that queued run."""
    R.flush_figures()
    asyncio.run(E.run_queued())


run("g = figure('Visible', 'off', 'ResizeFcn', 'laid = laid + 1;'); laid = 0; g2 = figure('SizeChangedFcn', 'sc = 1;'); sc = 0;")
shown()
check('a hidden figure does not run its ResizeFcn; one shown for the first time runs SizeChangedFcn', [num('laid'), num('sc')], [0, 1])
run("set(g, 'Visible', 'on');")
shown()
check('shown, it runs ResizeFcn (programs lay themselves out there)', num('laid'), 1)
shown()
check('and not again while its size stays', num('laid'), 1)
run("set(g, 'Position', [100 100 300 200]);")
shown()
check('a size the program sets runs it again', num('laid'), 2)
run("close(g, g2)")
run("set(f, 'CloseRequestFcn', 'asked = 1;'); asked = 0;")
ui({'type': 'closerequest', 'id': idof('f')})
check('the close button runs CloseRequestFcn', (num('asked'), num('ishandle(f)')), (1, True))
run("close(f)")
check('close runs it too', (num('asked'), num('ishandle(f)')), (1, True))
run("set(f, 'CloseRequestFcn', 'closereq');")
run("close(f)")
check('closereq closes', num('ishandle(f)'), False)
run("f = figure; set(f, 'CloseRequestFcn', ''); h = uicontrol(f, 'DeleteFcn', 'deleted = get(gcbo, ''Style'');');")
run("close(f)")
check('an empty CloseRequestFcn keeps the figure', num('ishandle(f)'), True)
run("close(f, 'force')")
check('close force deletes it, DeleteFcn first', (num('ishandle(f)'), text('deleted')), (False, 'pushbutton'))
run("close all force")

# ---- waiting for people ------------------------------------------------------------------------------------------------


def during(code, events, delay=0.05):
    """Run code while the page reports events, one by one."""
    async def go():
        R.take_output()
        job = asyncio.ensure_future(R.execute(code))
        for ev in events:
            await asyncio.sleep(delay)
            W.ui_event(json.dumps(ev(ev_ids()) if callable(ev) else ev))
        await asyncio.wait_for(job, 10)
        return R.take_output()
    return asyncio.run(go())


def ev_ids():
    return {k: v.id for k, v in R.BASE.items() if hasattr(v, 'id')}


run("f = figure; ok = uicontrol(f, 'String', 'OK', 'Callback', 'uiresume(gcbf)');")
out = during("uiwait(f); disp('resumed')", [lambda ids: {'type': 'control', 'id': ids['ok'], 'action': 'click'}])
check('uiwait waits until uiresume', out.strip(), 'resumed')
out = during("uiwait(f, 0.2); disp('timed out')", [])
check('uiwait with a time', out.strip(), 'timed out')
run("cb = uicontrol(f, 'Style', 'checkbox');")
out = during("waitfor(cb, 'Value', 1); disp('ticked')", [lambda ids: {'type': 'control', 'id': ids['cb'], 'action': 'toggle', 'on': True}])
check('waitfor a property', out.strip(), 'ticked')
run("b = uicontrol(f, 'Callback', 'n_ = n_ + 1;'); n_ = 0;")
out = during("for k = 1:20, pause(0.02); end, fprintf('%d\\n', n_)", [lambda ids: {'type': 'control', 'id': ids['b'], 'action': 'click'}], 0.02)
check('callbacks run during pause', out.strip(), '1')
out = during("t0 = tic; while toc(t0) < 0.3, drawnow; end, fprintf('%d\\n', n_)", [lambda ids: {'type': 'control', 'id': ids['b'], 'action': 'click'}], 0.05)
check('and at drawnow', out.strip(), '2')
out = during("t0 = tic; while toc(t0) < 0.3, drawnow nocallbacks; end, fprintf('%d\\n', n_)", [lambda ids: {'type': 'control', 'id': ids['b'], 'action': 'click'}], 0.05)
check('but not at drawnow nocallbacks', out.strip(), '2')
asyncio.run(E.run_queued())
check('they run when the program is done', num('n_'), 3)
run("delete(f)")
out = during("uiwait(f); disp('gone')", [])
check('uiwait on a deleted figure goes on', out.strip(), 'gone')
run("close all force")

# ---- dialogs ---------------------------------------------------------------------------------------------------------
run("cur = figure; h = msgbox(sprintf('First line\\nSecond line'), 'Note', 'warn');")
check('a message box is a figure with no number', (text("class(h)"), num("isempty(get(h, 'Number'))")), ('matlab.ui.Figure', True))
check('it is not the current figure', num('gcf == cur'), True)
check('nor found from the root', num("isempty(findobj(0, 'Name', 'Note'))"), True)
check('its lines', [c.str() for c in val('h').children[-2].props['String'].items()] if False else num("numel(get(findobj(h, 'Tag', 'MessageBox'), 'String'))"), 2)
check('its sign', num("isempty(get(findobj(h, 'Tag', 'IconAxes'), 'CData'))"), False)
d = serialize_figure(val('h'))
check('the page sees a dialog', (d['dialog'], d['menuBar'], d['toolBar']), (True, 'none', 'none'))
ui({'type': 'control', 'id': val('h').children[0].id if val('h').children[0].props.get('Tag') == 'OKButton' else [c for c in val('h').children if c.props.get('Tag') == 'OKButton'][0].id, 'action': 'click'})
check('OK closes it', num('ishandle(h)'), False)
for fn, title in (('errordlg', 'Error'), ('warndlg', 'Warning'), ('helpdlg', 'Help')):
    run(f"h = {fn}('Something');")
    check(f'{fn} has its title', text("get(h, 'Name')"), title)
run("h = msgbox('x', 'Box', 'custom', uint8(255 * ones(4, 4, 3)), []);")
check('a message box with a picture of its own, stretched over the sign\'s square', num("size(get(findobj(h, 'Tag', 'IconAxes'), 'CData'))"), [32.0, 32.0, 3.0])
run("ico = 3 * ones(13); ico(:, 1:4:13) = 1; ico(1:4:13, :) = 1; ico(2:4, 2:4) = 2; "
    "h2 = msgbox('y', 'Grid', 'custom', ico, [0 0 0; .5 .5 .6; 1 1 1]); c = get(findobj(h2, 'Tag', 'IconAxes'), 'CData');")
check('an indexed picture in its colours', (num('size(c)'), num('squeeze(c(1, 1, :))\''), num('squeeze(c(5, 5, :))\''), num('squeeze(c(16, 16, :))\'')),
      ([32.0, 32.0, 3.0], [0.0, 0.0, 0.0], [0.5, 0.5, 0.6], [1.0, 1.0, 1.0]))
check('findall finds the hidden dialogs', num("numel(findall(0, 'Name', 'Box'))"), 1)
run("hw = msgbox(repmat('ab ', 1, 40), 'Wide');")
check('a message box wraps its text at 75 letters', num("cellfun(@numel, get(findobj(hw, 'Tag', 'MessageBox'), 'String'))'"), [74.0, 45.0])
run("cbf = figure; uicontrol(cbf, 'Callback', 'seen = [numel(findobj(0, ''Name'', ''Box'')) numel(get(0, ''Children''))];');")
ui({'type': 'control', 'id': val('cbf').children[0].id, 'action': 'click'})
check('a callback sees them, by findobj and the root\'s Children', num('seen'), [1.0, float(len([f for f in STORE.figures.values() if f.valid]))])
run("w = waitbar(0, 'Working', 'Name', 'Job');")
check('a waitbar is a figure with a patch', (text("get(w, 'Name')"), num("numel(findobj(w, 'Type', 'patch'))")), ('Job', 1))
run("waitbar(0.5)")
check('waitbar(x) moves the newest bar', num("max(get(findobj(w, 'Type', 'patch'), 'XData'))"), 50)
run("waitbar(0.8, w, 'Nearly')")
check('and with a handle and a message', (num("max(get(findobj(w, 'Type', 'patch'), 'XData'))"), text("get(get(findobj(w, 'Type', 'axes'), 'Title'), 'String')")), (80, 'Nearly'))
run("w2 = waitbar(0, 'x', 'CreateCancelBtn', 'setappdata(gcbf, ''cancelling'', 1)');")
cancel = [c for c in val('w2').children if c.props.get('Tag') == 'TMWWaitbarCancelButton'][0]
ui({'type': 'control', 'id': cancel.id, 'action': 'click'})
check('a Cancel button', num("getappdata(w2, 'cancelling')"), 1)
ANSWERS['questdlg'] = 'No'
check('questdlg answers with the button', text("questdlg('Go on?', 'Q')"), 'No')
check('Yes, No and Cancel by default, Yes first', (ASKED[-1]['buttons'], ASKED[-1]['default']), (['Yes', 'No', 'Cancel'], 'Yes'))
text("questdlg('Which?', 'Q', 'Red', 'Blue', 'Blue')")
check('buttons of its own and the default', (ASKED[-1]['buttons'], ASKED[-1]['default']), (['Red', 'Blue'], 'Blue'))
ANSWERS['questdlg'] = None
check('closed: the answer is empty', text("questdlg('Go on?')"), '')
ANSWERS['inputdlg'] = ['Ada', '36']
run("a = inputdlg({'Name', 'Age'}, 'Who', [1; 1], {'x', 'y'});")
check('inputdlg: a cell of the answers', [x.str() for x in val('a').items()], ['Ada', '36'])
check('what it asked', (ASKED[-1]['prompts'], ASKED[-1]['defaults']), (['Name', 'Age'], ['x', 'y']))
ANSWERS['inputdlg'] = None
check('cancelled: {}', num("isempty(inputdlg('x'))"), True)
ANSWERS['listdlg'] = [0, 2]
run("[ix, ok] = listdlg('ListString', {'a', 'b', 'c'}, 'InitialValue', 2);")
check('listdlg', (num('ix'), num('ok')), ([1.0, 3.0], 1))
check('its initial choice', ASKED[-1]['initial'], [1])
ANSWERS['listdlg'] = None
run("[ix, ok] = listdlg('ListString', {'a'});")
check('cancelled', (num('isempty(ix)'), num('ok')), (True, 0))
ANSWERS['pickfile'] = {'path': TMP, 'names': ['b.ss'], 'filter': 1}
run("[fn, fp, fi] = uigetfile({'*.ss', 'Simple'; '*.sdk', 'Puzzle'}, 'Pick');")
check('uigetfile: name, folder and the type chosen', (text('fn'), text('fp'), num('fi')), ('b.ss', TMP + '/', 2))
check('the filters it gave', ASKED[-1]['filters'], [['*.ss', 'Simple'], ['*.sdk', 'Puzzle']])
ANSWERS['pickfile'] = None
run("[fn, fp, fi] = uigetfile('*.m');")
check('cancelled: zeros', (num('fn'), num('fp'), num('fi')), (0, 0, 0))
ANSWERS['pickfile'] = {'path': TMP, 'names': ['out.txt'], 'filter': 0}
run("[fn, fp] = uiputfile('*.txt', 'Save', 'out.txt');")
check('uiputfile', (text('fn'), ASKED[-1]['mode'], ASKED[-1]['name']), ('out.txt', 'save', 'out.txt'))
ANSWERS['pickfile'] = {'path': TMP + '/sub'}
check('uigetdir', text('uigetdir'), TMP + '/sub')
ANSWERS['menu'] = 1
check('menu: the button pressed', num("menu('Shape', 'Circle', 'Square')"), 2)
ANSWERS['color'] = [1, 0.5, 0]
check('uisetcolor', num('uisetcolor'), [1.0, 0.5, 0.0])
run("d = dialog('Name', 'Mine');")
check('dialog: a window of its own', (text("get(d, 'Name')"), text("get(d, 'WindowStyle')")), ('Mine', 'modal'))
run("close all force")

# ---- finding objects ---------------------------------------------------------------------------------------------------
run("fo = figure('Name', 'Find'); fa = axes(fo); hold(fa, 'on'); l1 = plot(fa, 1:3, 'Tag', 'part1'); "
    "l2 = plot(fa, 2:4, 'Tag', 'part2', 'HandleVisibility', 'off'); l3 = plot(fa, 3:5, 'Tag', 'other');")
check('findobj leaves out what HandleVisibility hides, findall not', (num("numel(findobj(fo, 'Type', 'line'))"), num("numel(findall(fo, 'Type', 'line'))")), (2, 3))
check('-regexp', (num("numel(findobj(fo, '-regexp', 'Tag', '^part'))"), num("numel(findall(fo, '-regexp', 'Tag', 'art'))")), (1, 2))
check('-or, and -not before a test', (num("numel(findobj(fo, 'Tag', 'part1', '-or', 'Tag', 'other'))"), num("numel(findobj(fo, '-not', 'Tag', 'part1', '-and', 'Type', 'line'))")), (2, 1))
check('-xor', num("numel(findobj(fo, 'Type', 'line', '-xor', 'Tag', 'other'))"), 1)
check('flat and -depth', (num("numel(findobj(fo, 'flat'))"), num("numel(findobj(fo, '-depth', 1))"), num("numel(findobj(fo, '-depth', 0, 'Type', 'line'))")), (1, 2, 0))
check('-property', num("numel(findobj(fa, '-property', 'Marker'))"), 2)
check('-function, on the object or on a property', (num("numel(findobj(fo, '-function', @(h) strcmp(get(h, 'Type'), 'line')))"), num("numel(findobj(fo, '-function', 'Tag', @(t) numel(t) == 5))")), (2, 2))
run("set(0, 'ShowHiddenHandles', 'on');")
check('the root\'s ShowHiddenHandles shows them to findobj', num("numel(findobj(fo, 'Type', 'line'))"), 3)
run("set(0, 'ShowHiddenHandles', 'off');")
check('and off again', (num("numel(findobj(fo, 'Type', 'line'))"), text("get(0, 'ShowHiddenHandles')")), (2, 'off'))
check('the root is among what findobj finds', text("get(findobj('Type', 'root'), 'Type')"), 'root')
run("tx = text(fa, 2, 9, 'outside'); set(l1, 'Clipping', 'off');")
kids = {c['id']: c for c in serialize_figure(val('fo'))['axes'][0]['children']}
check('text is not clipped to the axes, lines are unless asked', (kids[val('tx').id]['clip'], kids[val('l3').id]['clip'], kids[val('l1').id]['clip']), (False, True, False))
run("close all force")

# ---- programs written for older releases -----------------------------------------------------------------------------
run("fo = figure('Position', [100 100 500 400], 'DoubleBuffer', 'on', 'BackingStore', 'off'); fn = figure; figure(fo); "
    "fa = axes('Units', 'pixels', 'Position', [50 50 400 300], 'DrawMode', 'fast'); ln = line([0 1], [0 1], 'EraseMode', 'xor');")
check('their properties are kept: DoubleBuffer, DrawMode, EraseMode', (text("get(fo, 'DoubleBuffer')"), text("get(fo, 'BackingStore')"), text("get(fa, 'DrawMode')"),
                                                                       text("get(ln, 'EraseMode')")), ('on', 'off', 'fast', 'xor'))
run("z = zeros(1, 2); z(2) = line(fa, [0 1], [1 0]); h = []; h(1) = line(fa, [0 1], [0 0]);")
check('an object kept among numbers is its handle number, never a whole one', (num('z(1)'), num('mod(z(2), 1) > 0'), text('class(h)')),
      (0, True, 'matlab.graphics.chart.primitive.Line'))
run("set(z(2), 'Color', [1 0 0]);")
check('set, get, == and ishandle take the number', (num("get(z(2), 'Color')"), num("z(2) == findobj(fa, 'Color', [1 0 0])"), num('ishandle([z(2) 2.5])')),
      ([1.0, 0.0, 0.0], True, [True, False]))
run("delete(z(2));")
check('delete too; a figure is its number', (num('ishandle(z(2))'), num('double(fo) == round(double(fo))')), (False, True))
run("t1 = text(fa, 0, 0, 'a', 'FontSize', 30, 'FontUnits', 'Normalized'); t2 = text(fa, 0, 0, 'b', 'FontUnits', 'normalized', 'FontSize', 0.1);")
check("FontSize before FontUnits keeps the size, as a part of the axes' height", (text("get(t1, 'FontUnits')"), round(num("get(t1, 'FontSize')"), 4), num("get(t2, 'FontSize')")),
      ('normalized', 0.1333, 0.1))
run("set(t1, 'FontUnits', 'points');")
check('and back in points', round(num("get(t1, 'FontSize')"), 6), 30.0)
run("xlim(fa, [0 10]); ylim(fa, [0 5]); tu = text(fa, 200, 150, 'c', 'Units', 'Pixels');")
check("text(x, y, s, 'Units', u): x and y in those units", (text("get(tu, 'Units')"), num("get(tu, 'Position')")), ('pixels', [200.0, 150.0, 0.0]))
run("set(tu, 'Units', 'data');")
check('Units changed later: the place converted', num("get(tu, 'Position')"), [5.0, 2.5, 0.0])
run("set(tu, 'Units', 'normalized');")
check('to normalized', num("get(tu, 'Position')"), [0.5, 0.5, 0.0])
run("tb = text(fa, 1, 1, 'box', 'EdgeColor', 'k', 'Margin', 6, 'LineWidth', 2);")
d = serialize_figure(val('fo'))
tj = [c for c in d['axes'][0]['children'] if c['id'] == val('tb').id][0]
check("a text's box: its margin and line width go to the page", (tj['margin'], tj['lineWidth']), (6.0, 2.0))
check('a figure whose Position the program set opens at it', (d['placed'], serialize_figure(val('fn'))['placed']), (True, False))
check('default values: the factory ones read from the root', (num("get(0, 'DefaultUicontrolPosition')"), num("get(0, 'FactoryAxesFontSize')")), ([20.0, 20.0, 60.0, 20.0], 10))
run("set(0, 'DefaultAxesFontSize', 14); set(fo, 'DefaultLineLineWidth', 3); da = axes(fo); dl = line(da, [0 1], [0 1]); "
    "f9 = figure; dl2 = line([0 1], [0 1]); figure(fo);")
check("set on the root or a figure, new objects take them; another figure's line not", (num("get(da, 'FontSize')"), num("get(dl, 'LineWidth')"), num("get(dl2, 'LineWidth')")),
      (14, 3, 0.5))
run("set(0, 'DefaultAxesFontSize', 'remove'); da2 = axes(fo);")
check("'remove' takes one away", (num("get(da2, 'FontSize')"), num("get(0, 'DefaultAxesFontSize')")), (10, 10))
run("delete([da da2 f9]); axes(fa);")
check('a style may be shortened: push, radio, popup', [text(f"get(uicontrol(fo, 'Style', '{s}'), 'Style')") for s in ('push', 'radio', 'popup')],
      ['pushbutton', 'radiobutton', 'popupmenu'])
check('plot(x, y) with one x: a line of one point for each value', (num("numel(plot(fa, 1, [1 2 3], '-o'))"), num("numel(plot(fa, [1 2 3], 5, 'x'))")), (3, 3))
out = run("cla(fa); ode45(@(t, y) -y, [0 1], [1; 2])")
check('a solver asked for no output plots with odeplot, from t0 to tfinal', (out, num("numel(findobj(fa, 'Type', 'line'))"), num("get(fa, 'XLim')")),
      ('', 2, [0.0, 1.0]))
run("cla(fa); p1 = patch([0 1 1], [0 0 1], 'r'); p2 = patch([0 1 0], [0 1 1], [0 0 1]);")
check('patch adds to the axes as they are', num("numel(findobj(fa, 'Type', 'patch'))"), 2)
run("fill([0 1 1], [0 0 1], 'r');")
check('fill draws afresh unless held', num("numel(findobj(fa, 'Type', 'patch'))"), 1)
run("view(fa, 3); v3 = get(fa, 'CameraViewAngle'); view(fa, 2);")
check('CameraViewAngle: automatic, 6.6086 from above and 10.3396 in 3-D', (text("get(fa, 'CameraViewAngleMode')"), num("get(fa, 'CameraViewAngle')"), num('v3')),
      ('auto', 6.6086, 10.3396))
run("set(fa, 'CameraViewAngle', 2*atand(tand(6.6086/2)/2));")
check('a smaller one is manual, and the page draws the axes that much larger', (text("get(fa, 'CameraViewAngleMode')"), round(serialize_figure(val('fo'))['axes'][-1]['camZoom'], 9)),
      ('manual', 2.0))
run("set(fa, 'CameraViewAngleMode', 'auto'); camzoom(fa, 2); z2 = camva(fa); camva(fa, 'auto'); m = camva(fa, 'mode'); camva(fa, 5);")
check('camzoom narrows the angle; camva reads and sets it, and its mode', (round(num('z2'), 4), text('m'), num('camva(fa)'), text("camva(fa, 'mode')")),
      (3.307, 'auto', 5.0, 'manual'))
check('an angle of 180 or more is refused', 'less than 180' in run("set(fa, 'CameraViewAngle', 180)"), True)
run("close all force")

# ---- figure files ------------------------------------------------------------------------------------------------------
run("f = figure('Name', 'Round', 'Position', [100 100 500 380], 'Color', [0.9 0.95 1]); ax = axes('Position', [0.15 0.2 0.6 0.7]); "
    "l = plot(ax, 1:5, [2 4 3 5 1], 'r--o', 'LineWidth', 2, 'Tag', 'data'); hold(ax, 'on'); patch(ax, [1 2 2], [1 1 3], [0 0.5 0]); "
    "text(ax, 2, 4.5, 'peak', 'FontSize', 14); title(ax, 'The title'); xlabel(ax, 'time'); ylabel(ax, 'height'); xlim(ax, [0 6]); "
    "b = bar(ax, [1 2 3], [0.5 1 1.5], 'FaceColor', [1 0.5 0]); legend(ax, [l b], {'line', 'bars'}); "
    "cm = uicontextmenu(f); uimenu(cm, 'Label', 'Hello'); set(l, 'UIContextMenu', cm); m = uimenu(f, 'Label', 'Things'); "
    "uimenu(m, 'Label', 'Do', 'Callback', 'disp(''done'')', 'Accelerator', 'D'); "
    "uicontrol(f, 'String', 'Press', 'Position', [400 20 80 30], 'Callback', 'pressed = 1;', 'CreateFcn', 'made = made + 1;'); "
    "bg = uibuttongroup(f, 'Position', [0.8 0.3 0.18 0.3]); uicontrol(bg, 'Style', 'radiobutton', 'String', 'One', 'Position', [5 40 60 20]); "
    "r2 = uicontrol(bg, 'Style', 'radiobutton', 'String', 'Two', 'Position', [5 10 60 20]); set(bg, 'SelectedObject', r2); "
    "setappdata(f, 'note', 'kept'); made = 0;")
check('savefig writes a figure file', ('' == run("savefig(f, 'round.fig');"), os.path.isfile(os.path.join(TMP, 'round.fig'))), (True, True))
run("close all force; made = 0; g = openfig('round.fig');")
check('openfig: the figure again', (text("get(g, 'Name')"), num("get(g, 'Position')"), num("get(g, 'Color')")), ('Round', [100.0, 100.0, 500.0, 380.0], [0.9, 0.95, 1.0]))
run("a2 = findobj(g, 'Type', 'axes'); l2 = findobj(g, 'Tag', 'data');")
check('its axes, title, labels and limits', (num('numel(a2)'), text("get(get(a2, 'Title'), 'String')"), text("get(get(a2, 'XLabel'), 'String')"),
                                             text("get(get(a2, 'YLabel'), 'String')"), num("get(a2, 'XLim')")), (1, 'The title', 'time', 'height', [0.0, 6.0]))
check('a line with its style, data and context menu', (text("get(l2, 'LineStyle')"), text("get(l2, 'Marker')"), num("get(l2, 'LineWidth')"),
                                                       num("get(l2, 'YData')"), text("get(get(l2, 'UIContextMenu'), 'Type')")),
      ('--', 'o', 2, [2.0, 4.0, 3.0, 5.0, 1.0], 'uicontextmenu'))
check('a patch, a text, a bar series and the legend', (num("numel(findobj(g, 'Type', 'patch'))"), num("get(findobj(g, 'String', 'peak'), 'FontSize')"),
                                                       num("get(findobj(g, 'Type', 'bar'), 'FaceColor')"), num("numel(findall(g, 'Type', 'legend'))")),
      (1, 14, [1.0, 0.5, 0.0], 1))
check('controls with their callbacks; CreateFcn ran', (text("get(findobj(g, 'Style', 'pushbutton'), 'Callback')"), num('made'),
                                                       text("get(get(findobj(g, 'Type', 'uibuttongroup'), 'SelectedObject'), 'String')")), ('pressed = 1;', 1, 'Two'))
check('menus, application data and FileName', (text("get(findobj(g, 'Label', 'Do'), 'Accelerator')"), text("getappdata(g, 'note')"),
                                               text("get(g, 'FileName')")), ('D', 'kept', os.path.join(TMP, 'round.fig')))
run("g2 = openfig('round.fig', 'reuse');")
check("openfig 'reuse': the figure already open", num("g2 == g"), True)
run("close all force")

# a file in the layout of older releases: a lineseries, a group, labels named by handle number, a kind not made here
import scipy.io as sio  # noqa: E402

FIELDS = [('type', object), ('handle', object), ('properties', object), ('children', object), ('special', object)]


def fig_node(kind, handle, props, children=(), special=()):
    kids = np.zeros((len(children), 1), dtype=FIELDS)
    for i, c in enumerate(children):
        for k, _ in FIELDS:
            kids[i, 0][k] = c[k]
    return {'type': kind, 'handle': float(handle), 'properties': props, 'children': kids,
            'special': np.array([list(special)], float) if special else np.zeros((0, 0))}


labels = [fig_node('text', 101.0011 + i, {'String': s, 'Position': [0.5, 1.0, 0.0]}) for i, s in enumerate(['A title', 'x axis', 'y axis', ''])]
axes_node = fig_node('axes', 100.0016, {'Units': 'normalized', 'Position': [0.1, 0.1, 0.8, 0.8], 'XLim': [0.0, 10.0], 'XLimMode': 'manual',
                                        'Title': 101.0011, 'XLabel': 102.0011, 'YLabel': 103.0011, 'ZLabel': 104.0011},
                     [fig_node('graph2d.lineseries', 105.0013, {'XData': [[1.0, 2.0, 3.0]], 'YData': [[3.0, 1.0, 2.0]], 'Color': [[1.0, 0.0, 0.0]],
                                                                'Tag': 'old'}),
                      fig_node('hggroup', 106.0014, {}, [fig_node('line', 107.0015, {'XData': [[0.0, 1.0]], 'YData': [[0.0, 1.0]], 'Tag': 'inside'})]),
                      fig_node('scribe.arrow', 108.0016, {})] + labels, special=(4, 5, 6, 7))
root = fig_node('figure', 1.0, {'Units': 'pixels', 'Position': [50.0, 50.0, 420.0, 300.0], 'Name': 'Older', 'Color': [[1.0, 1.0, 1.0]]},
                [axes_node, fig_node('uicontrol', 109.0017, {'Style': 'pushbutton', 'String': 'Go', 'Callback': 'went = 1;',
                                                             'Units': 'pixels', 'Position': [10.0, 10.0, 60.0, 25.0]})])
sio.savemat(os.path.join(TMP, 'older.fig'), {'hgS_070000': root})
out = run("h = openfig('older.fig');")
check('an older layout opens: what was not made is named', 'scribe.arrow (1)' in out, True)
check('a lineseries is a line, a group what it holds', (num("get(findobj(h, 'Tag', 'old'), 'YData')"), text("get(findobj(h, 'Tag', 'old'), 'Type')"),
                                                        num("numel(findobj(h, 'Tag', 'inside'))")), ([3.0, 1.0, 2.0], 'line', 1))
check('labels found by their handle numbers', (text("get(get(gca, 'Title'), 'String')"), text("get(get(gca, 'XLabel'), 'String')"),
                                              text("get(get(gca, 'YLabel'), 'String')"), num("numel(findobj(h, 'Type', 'text'))")),
      ('A title', 'x axis', 'y axis', 0))
check('the figure and its button', (text("get(h, 'Name')"), num("get(h, 'Position')"), text("get(findobj(h, 'Style', 'pushbutton'), 'Callback')")),
      ('Older', [50.0, 50.0, 420.0, 300.0], 'went = 1;'))
sio.savemat(os.path.join(TMP, 'compact.fig'), {'hgM_070000': np.array([[1.0]])})
check("a file of the compact form only is refused, saying so", 'compact' in run("openfig('compact.fig')"), True)
sio.savemat(os.path.join(TMP, 'plain.mat'), {'x': np.array([[5.0]])})
check('a MAT-file that is no figure', 'holds no figure' in run("openfig('plain.mat')"), True)
run("hh = open('older.fig'); s = open('plain.mat');")
check('open: a figure file opens, a MAT-file loads', (text("get(hh, 'Name')"), num("s.x")), ('Older', 5))
run("close all force; f = figure('Name', 'Saved as'); uicontrol(f, 'Callback', @(s, e) disp(1));")
out = run("saveas(f, 'savedas.fig')")
check('saveas writes a figure file; a function handle callback is left out, with a warning', (os.path.isfile(os.path.join(TMP, 'savedas.fig')), 'function handles' in out),
      (True, True))
run("close all force; k = openfig('savedas.fig');")
check('and it opens', text("get(k, 'Name')"), 'Saved as')
run("close all force")

# ---- timers ----------------------------------------------------------------------------------------------------------
EVENTS.clear()
run("t = timer('TimerFcn', 'ticks = ticks + 1;', 'StartFcn', 'started = 1;', 'StopFcn', 'stopped = 1;', 'Period', 0.5, 'ExecutionMode', 'fixedRate', 'TasksToExecute', 3); ticks = 0; started = 0; stopped = 0;")
check('a timer is stopped at first', text("get(t, 'Running')"), 'off')
run("start(t)")
check('start runs StartFcn and asks the page for ticks', (num('started'), [e for e in EVENTS if e['type'] == 'timer'][-1]['op']), (1, 'start'))
check('Period cannot change while it runs', 'cannot be changed while the timer is running' in run("set(t, 'Period', 2)"), True)
for _ in range(3):
    ui({'type': 'timer', 'id': val('t').id})
check('each tick runs TimerFcn; after TasksToExecute it stops', (num('ticks'), text("get(t, 'Running')"), num('stopped')), (3, 'off', 1))
check('and tells the page', [e for e in EVENTS if e['type'] == 'timer'][-1]['op'], 'stop')
run("t2 = timer('TimerFcn', 'ticks = ticks + 1;', 'ExecutionMode', 'fixedRate', 'BusyMode', 'drop'); start(t2); ticks = 0;")
W.ui_event(json.dumps({'type': 'timer', 'id': val('t2').id}))
W.ui_event(json.dumps({'type': 'timer', 'id': val('t2').id}))
asyncio.run(E.run_queued())
check('a tick while one waits to run is dropped', num('ticks'), 1)
run("stop(t2)")
run("t3 = timer('TimerFcn', @(tm, ev) assignin('base', 'evtype', ev.Type));")
run("start(t3)")
ui({'type': 'timer', 'id': val('t3').id})
check('singleShot: once, with the event data', (text('evtype'), text("get(t3, 'Running')")), ('TimerFcn', 'off'))
check('timerfind', num("numel(timerfind)"), 3)
check('timerfind by property', num("numel(timerfind('ExecutionMode', 'singleShot'))"), 1)
run("delete(t3)")
check('a deleted timer is invalid', (num('isvalid(t3)'), num('numel(timerfindall)')), (False, 2))
run("set(t2, 'TimerFcn', 'stop(t2);'); start(t2)")
out = during("wait(t2); disp('waited')", [lambda ids: {'type': 'timer', 'id': ids['t2']}])
check('wait until a timer stops', out.strip(), 'waited')
run("delete(timerfindall)")

# ---- sound -----------------------------------------------------------------------------------------------------------


def sounds():
    return [e for e in EVENTS if e['type'] == 'sound']


def samples(e):
    return np.frombuffer(base64.b64decode(e['data']), '<f4').reshape(e['channels'], -1)


EVENTS.clear()
run("sound(sin(1:100), 8000)")
e = sounds()[-1]
check('sound sends the samples to the page', (e['rate'], e['channels'], samples(e).shape[1], round(float(samples(e)[0, 0]), 5)), (8000.0, 1, 100, round(float(np.sin(1.0)), 5)))
run("sound([2 -3 0.5])")
check('sound clips to -1..1, 8192 a second', (sounds()[-1]['rate'], [round(float(x), 3) for x in samples(sounds()[-1])[0]]), (8192.0, [1.0, -1.0, 0.5]))
run("soundsc([0 2 4], 4000)")
check("soundsc: the data's range becomes -1..1", [round(float(x), 3) for x in samples(sounds()[-1])[0]], [-1.0, 0.0, 1.0])
run("soundsc([0 2 4], 4000, [0 8])")
check('or the range given', [round(float(x), 3) for x in samples(sounds()[-1])[0]], [-1.0, -0.5, 0.0])
run("sound([zeros(4, 1), 0.5 * ones(4, 1)])")
check('two columns are left and right', (sounds()[-1]['channels'], [round(float(x), 2) for x in samples(sounds()[-1])[1]]), (2, [0.5] * 4))
check('three are refused', 'two columns' in run("sound(ones(4, 3))"), True)
n = len(sounds())
run("beep off; beep")
check('beep off silences beep', (len(sounds()), text('beep')), (n, 'off'))
run("beep on; beep")
check('beep plays a tone', len(sounds()), n + 1)

# ---- data kept with objects -----------------------------------------------------------------------------------------------
run("f = figure; b = uicontrol(f); setappdata(f, 'n', 5); guidata(b, struct('x', 7));")
check('getappdata', num("getappdata(f, 'n')"), 5)
check('isappdata', num("[isappdata(f, 'n') isappdata(f, 'm')]"), [True, False])
check('getappdata of a missing name is []', num("isempty(getappdata(f, 'm'))"), True)
check('guidata from any object of the figure', num("getfield(guidata(f), 'x')"), 7)
run("rmappdata(f, 'n')")
check('rmappdata', num("isappdata(f, 'n')"), False)
check('setappdata on the root', num("setappdata(0, 'r', 3); getappdata(0, 'r')") if False else (run("setappdata(0, 'r', 3);") or num("getappdata(0, 'r')")), 3)
run("close all force")

# ---- text in, by strmatch and textread -------------------------------------------------------------------------------
check('strmatch: the rows that start with', num("strmatch('Nor', {'Easy', 'Normal', 'Hard'})"), 2)
check("strmatch 'exact', blanks of a char matrix not counted", num("strmatch('a', ['abc'; 'a  '; 'xa '], 'exact')"), 2)
check('strmatch with no match', num("size(strmatch('q', {'a'}))"), [0.0, 1.0])
check('strmatch in a cell matrix: its elements down the columns', num("strmatch('A', {'A', 'B'; 'C', 'A'}')"), [1.0, 4.0])
with open(os.path.join(TMP, 'words.txt'), 'w') as fh:
    fh.write('...|.1.|...\n-----------\n2.3 x\n')
check('textread %s: the words over the lines', num("numel(textread('words.txt', '%s'))"), 4)
with open(os.path.join(TMP, 'cols.txt'), 'w') as fh:
    fh.write('name age\nAda 36\nBo 4\n% a comment\nCy 70\n')
run("[nm, ag] = textread('cols.txt', '%s %d', 'headerlines', 1, 'commentstyle', 'matlab');")
check('textread fields into outputs', ([x.str() for x in val('nm').items()], num('ag')), (['Ada', 'Bo', 'Cy'], [36.0, 4.0, 70.0]))
with open(os.path.join(TMP, 'csv.txt'), 'w') as fh:
    fh.write('1,2\n3,,\n')
run("[a, b] = textread('csv.txt', '%f %f', 'delimiter', ',');")
check('an empty field is emptyvalue (0)', (num('a'), num('b')), ([1.0, 3.0], [2.0, 0.0]))
run("x = textread('csv.txt', '%f', 1, 'delimiter', ',');")
check('textread a count of times', num('x'), 1)

# ---- programs made for MATLAB load toolbar pictures ----------------------------------------------------------------------
from plab.builtins.uifun import write_icons  # noqa: E402
write_icons(os.path.join(TMP, 'mroot'))
run(f"s = load('{TMP}/mroot/toolbox/matlab/icons/opendoc.mat');")
check('the pictures are there, drawn here', (num("size(s.cdata)"), num("any(isnan(s.cdata(:)))")), ([16.0, 16.0, 3.0], True))

sys.exit(check.done())
