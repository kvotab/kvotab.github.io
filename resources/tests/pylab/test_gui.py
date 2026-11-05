"""User interfaces, run natively (CPython with numpy and scipy): the
controls, panels, tables, tabs, menus and toolbars and their properties;
what people do with them (the page's events, as uievents.handle takes
them) and the callbacks that answer, by text, function handle and cell;
gcbo, gcbf and gco; uiwait, waitfor, drawnow and pause letting callbacks
run; the dialogs (the page's answers stood in for); timers; data kept with
objects; textread and strmatch; annotations as objects; the files saveas,
print and exportgraphics ask the page for; getframe, frame2im, im2frame and
movie; modal windows; and the description the page builds from.

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

# ---- annotations, figure files, frames and modal windows ----------------------------------------------------------------
run("close all force; f = figure; plot(1:3); h = annotation('arrow', [0.2 0.5], [0.3 0.6]);")
check('an arrow annotation: its type and class', (text("get(h, 'Type')"), text('class(h)')), ('arrowshape', 'matlab.graphics.shape.Arrow'))
check('Position from X and Y', num("get(h, 'Position')"), [0.2, 0.3, 0.3, 0.3])
run("set(h, 'Position', [0.1 0.2 0.4 0.2]);")
check('X and Y from Position', (num("get(h, 'X')"), num("get(h, 'Y')")), ([0.1, 0.5], [0.2, 0.4]))
check('a head style is checked', 'HeadStyle must be one of' in run("set(h, 'HeadStyle', 'star')"), True)
check('X must have two ends', 'two numbers' in run("set(h, 'X', [1 2 3])"), True)
check("not among the figure's Children; findobj finds it by Type", (num("numel(get(f, 'Children'))"), num("numel(findobj(f, 'Type', 'arrowshape'))")), (1, 1))
run("b = annotation('textbox', [0.1 0.7 0.3 0.1], 'String', {'one', 'two'}, 'FitBoxToText', 'on', 'BackgroundColor', 'y'); "
    "d = annotation(f, 'doublearrow', [0.6 0.9], [0.5 0.5], 'Head1Style', 'diamond'); e = annotation('ellipse', [0.5 0.1 0.2 0.1], 'FaceColor', 'g');")
shapes = {a['shape']: a for a in serialize_figure(val('f'))['annotations']}
check('the page is told each kind, where and how', (sorted(shapes), shapes['textbox']['string'], shapes['textbox']['fitBox'], shapes['textbox']['background'],
      shapes['doublearrow']['head1']['style'], shapes['doublearrow']['head2']['style'], shapes['arrow']['x'], shapes['ellipse']['faceColor']),
      (['arrow', 'doublearrow', 'ellipse', 'textbox'], ['one', 'two'], True, [1.0, 1.0, 0.0], 'diamond', 'vback2', [0.1, 0.5], [0.0, 1.0, 0.0]))
check('a textbox gives its lines back as a cell', num("iscell(get(b, 'String'))"), True)
check('an unknown kind is refused', "Unknown annotation type 'star'" in run("annotation('star')"), True)
check('a figure file leaves annotations out, saying so', 'Annotations' in run("savefig(f, 'withshapes.fig')"), True)
run("delete(h);")
check('delete takes it away', [a['shape'] for a in serialize_figure(val('f'))['annotations']].count('arrow'), 0)

ANSWERS['render'] = lambda req: base64.b64encode(f"{req['format']}:{req['scale']:g}".encode()).decode()
for cmd, fname, want in (("saveas(f, 'p.pdf')", 'p.pdf', 'pdf:2'), ("print('-dsvg', 'q')", 'q.svg', 'svg:2'), ("print(f, 'r.png', '-r300')", 'r.png', 'png:3.125'),
                         ("saveas(f, 'out.dat', 'png')", 'out.dat', 'png:2'), ("exportgraphics(gca, 'a.eps', 'Resolution', 144)", 'a.eps', 'eps:1.5'),
                         ("print('-dtiff', 'z')", 'z.tif', 'tif:2'), ("saveas(f, 'k', 'jpeg')", 'k.jpg', 'jpg:2'), ("saveas(f, 'm.bmp')", 'm.bmp', 'bmp:2')):
    run(cmd)
    pth = os.path.join(TMP, fname)
    check(f'{cmd}: the kind and size asked of the page, written as {fname}', open(pth, 'rb').read().decode() if os.path.isfile(pth) else None, want)
check('a .gif is refused, naming the formats there are', 'Unable to write a .gif file here' in run("saveas(f, 'x.gif')"), True)
ANSWERS['render'] = None

ANSWERS['frame'] = lambda req: {'width': 2, 'height': 1, 'data': base64.b64encode(bytes([255, 0, 0, 0, 255, 0])).decode()}
run("F = getframe; ax = gca;")
check('getframe asks for the current axes', (ASKED[-1]['type'], ASKED[-1]['axes'] == val('ax').id), ('frame', True))
check('cdata: rows x columns x 3 of uint8; colormap []', (num('size(F.cdata)'), text('class(F.cdata)'), num('F.cdata(1, 2, 2)'), num('isempty(F.colormap)')),
      ([1.0, 2.0, 3.0], 'uint8', 255, True))
run("getframe(f, [10 20 30 40]);")
check('getframe(fig, rect): the whole figure and the rectangle', (ASKED[-1]['axes'], ASKED[-1]['rect']), (None, [10.0, 20.0, 30.0, 40.0]))
check('frame2im gives the picture', num('isequal(frame2im(F), F.cdata)'), True)
check('im2frame of doubles makes uint8', (text("class(getfield(im2frame(rand(2, 2, 3)), 'cdata'))"), num("getfield(im2frame(ones(1, 1, 3)), 'cdata')")),
      ('uint8', [255.0, 255.0, 255.0]))
check('an indexed picture needs its colormap', 'needs its colormap' in run('im2frame(magic(3))'), True)
check('movie plays the frames', run('movie(F, 2, 100)'), '')
ANSWERS['frame'] = None
check('getframe with no page to draw it says so', 'could not be drawn' in run('getframe(f)'), True)

run("m = msgbox('hi', 'T', 'modal'); n = msgbox('hi'); dd = dialog;")
check("msgbox 'modal' and dialog are modal windows; a plain msgbox is not",
      [serialize_figure(val(x))['windowStyle'] for x in ('m', 'n', 'dd')], ['modal', 'normal', 'modal'])
run("close all force")
run("d = dialog('Name', 'Mine'); f = figure; close(f); h = plot(1:3); p = ancestor(h, 'figure');")
check("a dialog's window never becomes the current figure when another closes", (num('p == d'), num("strcmp(get(p, 'Name'), 'Mine')")), (False, False))
run("close all force; n = numel(findall(0, 'Type', 'figure'));")
check("close all force closes the dialog's window too", num('n'), 0)

# ---- bubble charts ---------------------------------------------------------------------------------------------------
run("f = figure; b = bubblechart([1 2 3 4], [4 3 2 1], [10 20 30 40]); bubblesize([4 20]); hold on; "
    "b2 = bubblechart([1 2], [2 2], [5 100], [0.2 0.6 0.2]); hold off;")
kids = {c['id']: c for c in serialize_figure(val('f'))['axes'][0]['children']}
d1, d2 = (np.round(np.frombuffer(base64.b64decode(kids[val(x).id]['bubbleSize']['$']), float), 3).tolist() for x in ('b', 'b2'))
check('bubble diameters in points: areas even between the axes-wide smallest and largest sizes', (d2, d1[0] < d1[1] < d1[2] < d1[3]),
      ([4.0, 20.0], True))
check('their faces 0.6 opaque, edges whole', (kids[val('b').id]['markerFaceAlpha'], kids[val('b').id]['markerEdgeAlpha']), (0.6, 1.0))
run("bubblelim([0 10]);")
kids = {c['id']: c for c in serialize_figure(val('f'))['axes'][0]['children']}
d1 = np.round(np.frombuffer(base64.b64decode(kids[val('b').id]['bubbleSize']['$']), float), 3).tolist()
check('sizes past bubblelim get the end bubbles', d1, [20.0] * 4)
run("close all force")

# ---- the figure's property editor (worker_api.inspect_object / inspect_change) ------------------------------
run("close all force; f = figure('Name', 'Ed'); h = plot(1:5, [3 1 4 1 5], 'r--o', 'DisplayName', 'data'); ax = gca; "
    "title('Hello'); xlabel('x'); lg = legend; cb = colorbar; t = text(2, 3, 'note'); an = annotation('arrow'); "
    "sgtitle('Big'); b = uicontrol('String', 'Go');")


def insp(name_or_id):
    i = name_or_id if isinstance(name_or_id, int) else idof(name_or_id)
    return json.loads(W.inspect_object(i))


def prop(d, name):
    return next(p for g in d['groups'] for p in g['props'] if p['name'] == name)


def change(name, prop_name, payload):
    EVENTS.clear()
    d = json.loads(W.inspect_change(idof(name), prop_name, json.dumps(payload)))
    return d.get('error'), any(e.get('type') == 'figures' for e in EVENTS)


d = insp('f')
check("the editor's tree: the figure, its super title, axes with title and labels, what is plotted, legend, colorbar "
      "and its label, the annotation and the control",
      [(r['depth'], r['label']) for r in d['tree']],
      [(0, 'Figure 1: Ed'), (1, "Super title 'Big'"), (1, "Axes 'Hello'"), (2, "Title 'Hello'"), (2, "X label 'x'"),
       (2, 'Y label'), (2, "Line 'data'"), (2, "Text 'note'"), (2, 'Legend'), (2, 'Colorbar'), (3, 'Label'), (1, 'Arrow'),
       (1, "UIControl 'Go'")])
check('the tree names its objects by id, as the page draws them', [r['id'] for r in d['tree']][:3],
      [idof('f'), val('f').sgtitle.id, idof('ax')])
d = insp('h')
check("a line's common properties come first, in their order", [p['name'] for p in d['groups'][0]['props']],
      ['Color', 'LineStyle', 'LineWidth', 'Marker', 'MarkerSize', 'MarkerFaceColor', 'DisplayName'])
check('each with the field that suits it',
      [(prop(d, n)['kind'], prop(d, n)['value']) for n in ('Color', 'LineStyle', 'LineWidth', 'XData', 'Visible', 'MarkerFaceColor')],
      [('color', [1.0, 0.0, 0.0]), ('enum', '--'), ('number', '0.5'), ('array', '[1 2 3 4 5]'), ('onoff', True), ('color', 'none')])
check("a colour's words are offered", prop(d, 'MarkerFaceColor')['options'], ['none', 'auto', 'flat'])
check("the other groups follow, by name, and last what is kept but not drawn", [g['name'] for g in d['groups']],
      ['Common', 'Markers', 'Data', 'Identity and interaction', 'Callbacks', 'Kept, not drawn'])
check('Parent is a link to the axes; Type and UserData are only shown',
      (prop(d, 'Parent')['kind'], prop(d, 'Parent')['link'], prop(d, 'Type')['kind'], prop(d, 'UserData')['kind']),
      ('link', idof('ax'), 'readonly', 'readonly'))
d = insp('ax')
check("the axes' title and labels are their text, as lines", [prop(d, n)['value'] for n in ('Title', 'XLabel', 'YLabel')],
      [['Hello'], ['x'], ['']])
check("limits in auto mode show the limits drawn; the mode is a choice", (prop(d, 'XLim')['value'], prop(d, 'XLimMode')['options']),
      ('[1 5]', ['auto', 'manual']))
check('the colormap is a choice of named maps', (prop(d, 'Colormap')['kind'], 'jet' in prop(d, 'Colormap')['options']), ('colormap', True))
check('a legend lists its strings', prop(insp('lg'), 'String')['value'], ['data'])
check("a y label reads upwards (Rotation 90), a title not", (num("get(get(ax, 'YLabel'), 'Rotation')"), num("get(get(ax, 'Title'), 'Rotation')")),
      (90.0, 0.0))
d = insp(val('ax').title.id)
check("a title's turn can be changed; where it stands is its axes' to say",
      [(prop(d, n)['kind'], prop(d, n).get('note')) for n in ('Rotation', 'Position', 'HorizontalAlignment')],
      [('number', None), ('readonly', 'placed by its axes'), ('readonly', 'placed by its axes')])
check("a colorbar's label is turned by its colorbar", (prop(insp(val('cb').label.id), 'Rotation')['kind'], prop(insp(val('cb').label.id), 'Rotation')['note']),
      ('readonly', 'placed by its colorbar'))
check("a figure's callbacks are text", (prop(insp('f'), 'CloseRequestFcn')['kind'], prop(insp('f'), 'CloseRequestFcn')['value']),
      ('callback', 'closereq'))

check('a colour as [r g b] is set, and the figure drawn again', change('h', 'Color', {'kind': 'color', 'value': [0, 0.5, 1]}), (None, True))
check('... as the language has it', num("get(h, 'Color')"), [0.0, 0.5, 1.0])
change('h', 'Color', {'kind': 'color', 'value': 'green'})
check('a colour by name', num("get(h, 'Color')"), [0.0, 1.0, 0.0])
change('h', 'Color', {'kind': 'color', 'value': '#ff8000'})
check('a colour by hex code', num("round(get(h, 'Color') * 255)"), [255.0, 128.0, 0.0])
change('h', 'Color', {'kind': 'color', 'value': '0 0 1'})
check('a colour typed as numbers', num("get(h, 'Color')"), [0.0, 0.0, 1.0])
check('a colour that is none is refused with the message set gives, and nothing is drawn',
      change('h', 'Color', {'kind': 'color', 'value': 'blurple'}), ("Invalid color name or hex code 'blurple'.", False))
change('h', 'LineStyle', {'kind': 'enum', 'value': ':'})
change('h', 'LineWidth', {'kind': 'number', 'value': '2.5'})
change('h', 'Visible', {'kind': 'onoff', 'value': False})
change('h', 'YData', {'kind': 'array', 'value': '[5, 4 3 2 1]'})
check('a choice, a number, on/off and numbers', (text("get(h, 'LineStyle')"), num("get(h, 'LineWidth')"), text("get(h, 'Visible')"),
                                                 num("get(h, 'YData')")), (':', 2.5, 'off', [5.0, 4.0, 3.0, 2.0, 1.0]))
check('a number is read, never run', change('h', 'LineWidth', {'kind': 'number', 'value': '1+1'})[0], "'1+1' is not a number.")
check('nor is a call', change('h', 'YData', {'kind': 'array', 'value': 'disp(7)'})[0], "'disp(7)' is not a number.")
check('rows of numbers must be as long', change('h', 'YData', {'kind': 'array', 'value': '[1 2; 3]'})[0],
      'Each row needs the same number of values.')
change('ax', 'XLim', {'kind': 'array', 'value': '[-pi pi]'})
check('pi and Inf are numbers; limits set are manual', (num("round(get(ax, 'XLim') * 1e4)"), text("get(ax, 'XLimMode')")),
      ([-31416.0, 31416.0], 'manual'))
check("limits the wrong way round get set's message", change('ax', 'YLim', {'kind': 'array', 'value': '[1 0]'})[0],
      'Value must be a 1x2 vector of numeric type in which the second element is larger than the first and may be Inf.')
change('ax', 'Title', {'kind': 'lines', 'value': ['Top', 'second']})
check('a title of two lines', text("strjoin(get(get(ax, 'Title'), 'String'), '|')"), 'Top|second')
change('ax', 'XTickLabel', {'kind': 'lines', 'value': ['a', 'b']})
check('tick labels typed one a line are set, and manual', (text("strjoin(get(ax, 'XTickLabel'), '|')"), text("get(ax, 'XTickLabelMode')")),
      ('a|b', 'manual'))
change('lg', 'String', {'kind': 'lines', 'value': ['first']})
change('cb', 'Label', {'kind': 'lines', 'value': ['Temp']})
check("legend strings name the lines; a colorbar's label is its Label's text", (text("get(h, 'DisplayName')"), text('cb.Label.String')),
      ('first', 'Temp'))
change('f', 'Colormap', {'kind': 'colormap', 'value': 'gray', 'rows': 64})
check('a named colormap, as many rows as before', num("size(colormap(f))"), [64.0, 3.0])
check('one not named is refused', change('f', 'Colormap', {'kind': 'colormap', 'value': 'magma2'})[0], "'magma2' is not a colormap.")
change('f', 'Name', {'kind': 'text', 'value': "it's; disp(1)"})
check('text is kept as typed', text("get(f, 'Name')"), "it's; disp(1)")
change('f', 'WindowButtonDownFcn', {'kind': 'callback', 'value': "@(s, e) disp('hi')"})
check('a callback starting with @ is a function handle', text("class(get(f, 'WindowButtonDownFcn'))"), 'function_handle')
change('f', 'WindowButtonDownFcn', {'kind': 'callback', 'value': '@disp'})
check('... also by name', text("func2str(get(f, 'WindowButtonDownFcn'))"), 'disp')
check('but only a handle', change('f', 'WindowButtonDownFcn', {'kind': 'callback', 'value': '@disp; clear all'})[0],
      "'@disp; clear all' is not a function handle.")
change('f', 'WindowButtonDownFcn', {'kind': 'callback', 'value': ''})
check('a property only shown is not changed', change('f', 'Number', {'kind': 'number', 'value': '5'})[0], 'Number cannot be changed here.')
change('b', 'Enable', {'kind': 'enum', 'value': 'inactive'})
check("a control's Enable takes inactive", text("get(b, 'Enable')"), 'inactive')
check("a control's style is a choice", prop(insp('b'), 'Style')['options'][:3], ['pushbutton', 'togglebutton', 'radiobutton'])
run("delete(t)")
check('a deleted object is said to be gone', json.loads(W.inspect_object(idof('t'))), {'ok': False, 'error': 'That object has been deleted.'})
run("figure; hh = histogram(randn(100, 1), 10);")
check("a histogram's bins are shown, not changed (set would not count again)", (prop(insp('hh'), 'NumBins')['kind'],
                                                                                 prop(insp('hh'), 'BinEdges')['kind']), ('readonly', 'readonly'))
run("figure; yyaxis left; plot(1:3); yyaxis right; plot(3:-1:1); ylabel('R');")
check('the right y-axis of yyaxis is in the tree with its label and plot',
      [r['label'] for r in json.loads(W.inspect_object(val('f').id if False else STORE.current.id))['tree']][-3:],
      ['Axes (right y)', "Y label 'R'", 'Line'])
run("figure; yyaxis left; plot(1:3); ylabel('L'); yyaxis right; plot(10:10:30); ylabel('R'); xlabel('X'); title('T'); xlim([0 4]); ax = gca;")
check("yyaxis: the x label, title and x limits given on the right side are the axes' own (one x-axis, one title)",
      (text("ax.XLabel.String"), text("ax.Title.String"), num("ax.XLim")), ('X', 'T', [0.0, 4.0]))
_own = val('ax').yy_owner
check('... and stored with the left side, whose x-axis and title are drawn', (_own.xlabel.get_value('String').str(), tuple(np.asarray(_own.props['XLim'], float).reshape(-1))), ('X', (0.0, 4.0)))
run("yyaxis left; ax.YLim = [0 5]; b = gca;")
check("yyaxis: a handle taken on either side reads and sets the active side's y-axis", (text("ax.YLabel.String"), num("b.YLim"), text("b.YLabel.String")), ('L', [0.0, 5.0], 'L'))
run("yyaxis right;")
check('... and the other side once that is active', (text("b.YLabel.String"), text("ax.YLabel.String")), ('R', 'R'))

run("figure; plot(1:3, [1:3; 2:4; 3:5]'); lgA = legend('a', '', 'c'); figure; plot(1:3, [1:3; 2:4]'); lgB = legend;")
check('legend: a name given empty stays empty (an entry without text); only unnamed lines get dataN',
      (text("strjoin(lgA.String, '|')"), text("strjoin(lgB.String, '|')")), ('a||c', 'data1|data2'))

# what is changed is drawn: charts laid out again, on/off kept as on/off, log axes with bars
run("figure; hb = bar([1 2 3]); hold on; ha = area([1 2 3] + 5); hold off;")
for pname, value, key, want in (('BarWidth', '0.3', 'width', 0.3), ('BaseValue', '1', 'bottom', [1.0, 1.0, 1.0]), ('YData', '[3 2 1]', 'top', [3.0, 2.0, 1.0])):
    change('hb', pname, {'kind': 'number' if ' ' not in value else 'array', 'value': value})
    v = val('hb').extra[key]
    check(f"a bar's {pname} changed lays the bars out again", v if isinstance(v, float) else np.asarray(v).round(6).tolist(), want)
change('ha', 'YData', {'kind': 'array', 'value': '[1 1 1]'})
check("an area's YData changed draws it again", val('ha').extra['top'].tolist(), [1.0, 1.0, 1.0])
change('hb', 'Horizontal', {'kind': 'onoff', 'value': True})
run("set(hb, 'Horizontal', 'off');")
check("on/off set as text: 'off' is off (a bar's Horizontal)", val('hb').props['Horizontal'], False)
run("figure; bar([1 2 3]); set(gca, 'YScale', 'log'); yl = ylim;")
check('bars on a log axis start a tenth below the smallest positive end', num('yl'), [0.1, 10.0])
run("figure; [~, hc] = contour(peaks(10));")
change('hc', 'LevelList', {'kind': 'array', 'value': '[0 2]'})
check('a contour traced again at the levels given, which stay', (val('hc').extra['levels'].tolist(), val('hc').props['LevelListMode']), ([0.0, 2.0], 'manual'))
run("figure; hp = pie([1 2 3]); figure; hq = quiver(1:3, 1:3, [1 0 1], [0 1 1]);")
check("a pie's Labels are the labels drawn", prop(insp('hp'), 'Labels')['value'], ['17%', '33%', '50%'])
change('hp', 'Labels', {'kind': 'lines', 'value': ['a', 'b', 'c']})
check('... and new ones are drawn', val('hp').extra['labels'], ['a', 'b', 'c'])
s0 = val('hq').extra['scale']
change('hq', 'AutoScaleFactor', {'kind': 'number', 'value': '0.45'})
check("a quiver's AutoScaleFactor scales its arrows again", round(val('hq').extra['scale'] / s0, 6), 0.5)
check("a bar offers a bar's properties, not a histogram's or a quiver's", [n in [p['name'] for g in insp('hb')['groups'] for p in g['props']]
                                                                           for n in ('BarWidth', 'NumBins', 'AutoScaleFactor', 'Marker')], [True, False, False, False])
run("figure; polarplot(1:3); pax = gca;")
names = [p['name'] for g in insp('pax')['groups'] for p in g['props']]
check('polar axes offer no Cartesian x, y and z settings', ([n for n in names if n[0] in 'XYZ' and n[1].isupper()], 'GridColor' in names), ([], True))
run("figure; tb = plot(1:3); ax2 = gca; t1 = title('T'); set(ax2, 'FontSize', 14); set(ax2, 'TitleFontWeight', 'normal');")
check("the axes' FontSize carries to its title and labels; TitleFontWeight to its title",
      (num("get(t1, 'FontSize')"), num("get(get(ax2, 'XLabel'), 'FontSize')"), text("get(t1, 'FontWeight')")), (14.0, 14.0, 'normal'))
d = serialize_figure(STORE.current)['axes'][0]
check('the page is sent the tick font, length and minor ticks, the minor grid and the size multipliers',
      [k in d for k in ('fontName', 'fontWeight', 'tickLabelInterpreter', 'tickLength', 'xminortick', 'minorGridAlpha', 'minorGridLineStyle',
                        'titleSize', 'labelSize')], [True] * 9)

EVENTS.clear()
run("inspect(h)")
check('inspect(h) asks the page to show h in its figure', [e for e in EVENTS if e['type'] == 'inspect'],
      [{'type': 'inspect', 'figure': idof('f'), 'id': idof('h')}])
EVENTS.clear()
run("plotedit(f, 'on'); plotedit off; plotedit")
check("plotedit turns a figure's edit mode on, off, or switches it", [(e['type'], e['on']) for e in EVENTS if e['type'] == 'plotedit'],
      [('plotedit', True), ('plotedit', False), ('plotedit', None)])
check('inspect needs a graphics object', 'must be a graphics object' in run('inspect(1e9)'), True)
check("plotedit takes on or off", "Use 'on' or 'off'." in run("plotedit maybe"), True)
check('plotedit needs a figure', 'The input must be a figure.' in run("plotedit(1e9, 'on')"), True)
run("close all force")

# quiver at scattered points (a mesh's nodes): arrows as long as the room each point has in the area they cover
run("figure; rng default; hs = quiver(rand(50, 1), rand(50, 1), ones(50, 1), zeros(50, 1));")
_X, _Y = np.asarray(val('hs').props['XData'], float), np.asarray(val('hs').props['YData'], float)
check('quiver at scattered points: the longest arrow 0.9 of the room each point has (the smallest x step made it 1e-17 long)',
      round(val('hs').extra['scale'] / (0.9 * np.sqrt(np.ptp(_X) * np.ptp(_Y) / 50)), 9), 1.0)
run("close all force")

# quiver and quiver3: their sizes checked; quiver3 holds Z and W and draws in 3-D
check('quiver refuses U and V of different sizes', 'U and V must be the same size.' in run("figure; quiver(eye(2), eye(2), eye(3), eye(2))"), True)
check("quiver refuses X and Y that fit U's grid neither way", 'must be the same size' in run("quiver(1:4, 1:2, ones(2, 3), ones(2, 3))"), True)
check('quiver3 refuses Z, U, V and W of different sizes', ['Z, U, V and W must be the same size.' in run(c) for c in
      ("quiver3(eye(2), eye(2), eye(3), eye(2), eye(2), eye(2))", "quiver3(eye(2), eye(2), eye(2), eye(3))")], [True, True])
run("""close all force; [X, Y] = meshgrid(1:3, 1:2); Z = X + Y; q = quiver3(X, Y, Z, ones(2, 3), 2*ones(2, 3), 3*ones(2, 3));
qv = get(gca, 'View'); qz = zlim; figure; q2 = quiver3(Z, ones(2, 3), ones(2, 3), ones(2, 3), 'off');
figure; q3 = quiver(1:3, 1:2, ones(2, 3), ones(2, 3), 0.5, 'r');""")
q = val('q')
check('quiver3 keeps Z and W, and gives fresh axes a 3-D view without the box', (np.shape(q.props['ZData']), float(np.asarray(q.props['WData']).flat[0]), num('qv'), q.parent.props['Box']),
      ((2, 3), 3.0, [-37.5, 30.0], False))
check("quiver3's z-limits take in the arrows' tips", num('qz(2)') >= 5 + 3 * q.extra['scale'] - 1e-9, True)
check("quiver3(Z, U, V, W, 'off'): the grid 1:n, 1:m and the arrows as given", (np.asarray(val('q2').props['XData']).tolist(), val('q2').extra['scale']),
      ([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]], 1.0))
check("quiver's vectors X and Y spread over U's grid; a scale and a LineSpec", (np.shape(val('q3').props['XData']), num('q3.AutoScaleFactor'), num('q3.Color')),
      ((2, 3), 0.5, [1.0, 0.0, 0.0]))
from plab.graphics_base import serialize_child
sc = serialize_child(q, q.parent)
check('the page is sent quiver3\'s Z and W', ('zData' in sc, 'wData' in sc), (True, True))
run("close all force")

# ver with an output: a struct array, nothing printed
out = run("v = ver; vn = ver('NumPy'); ve = ver('nothing');")
check('v = ver prints nothing and gives a struct array of Name, Version, Release and Date', (out.strip(), val('v').shape, val('v').keys, text('v(1).Name')),
      ('', (1, 4) if 'scipy' in sys.modules else (1, 3), ['Name', 'Version', 'Release', 'Date'], 'PyLAB'))
check("ver(name) keeps that element; an unknown name gives an empty struct", (val('vn').shape, text('vn.Name'), val('ve').shape), ((1, 1), 'NumPy', (0, 0)))

# WindowStyle: its four values, any case; the page docking a figure into the desktop and taking it out
out = run("close all force; wf = figure; set(wf, 'WindowStyle', 'Docked'); ws1 = get(wf, 'WindowStyle');")
check("WindowStyle takes 'docked' (in any case) and is shown as given", text('ws1'), 'docked')
check('WindowStyle refuses other values', "WindowStyle is 'normal', 'modal', 'docked' or 'alwaysontop'" in run("set(wf, 'WindowStyle', 'floating')"), True)
W.figure_event(json.dumps({'type': 'windowstyle', 'id': idof('wf'), 'style': 'normal'}))
ws2 = text("get(wf, 'WindowStyle')")
W.figure_event(json.dumps({'type': 'windowstyle', 'id': idof('wf'), 'style': 'docked'}))
check("the page's docking reaches WindowStyle (normal, then docked), and the figure's data says so",
      (ws2, text("get(wf, 'WindowStyle')"), serialize_figure(val('wf'))['windowStyle']), ('normal', 'docked', 'docked'))
run("set(groot, 'DefaultFigureWindowStyle', 'docked'); wg = figure; ws3 = get(wg, 'WindowStyle'); set(groot, 'DefaultFigureWindowStyle', 'normal'); close all force")
check('DefaultFigureWindowStyle docks new figures', text('ws3'), 'docked')

# plotting into a uifigure's axes makes no figure of its own, and a hidden figure is not the root's CurrentFigure
run("close all force; uf = uifigure; uax = uiaxes(uf); plot(uax, 1:3); line(uax, [1 2], [2 1]); nfig = numel(findall(groot, 'Type', 'figure')); "
    "nl = numel(uax.Children); cf0 = isempty(get(groot, 'CurrentFigure')); hf = figure; cf1 = isequal(get(groot, 'CurrentFigure'), hf); "
    "set(hf, 'HandleVisibility', 'off'); cf2 = isempty(get(groot, 'CurrentFigure')); delete(uf); close all force")
check('plot and line into uiaxes draw there and make no other figure; CurrentFigure skips hidden handles as gcf does',
      (val('nfig'), val('nl'), val('cf0'), val('cf1'), val('cf2')), (1, 2, True, True, True))

# a value in a handle's property changed in place goes back through the setter: a grid child's Layout, a bar's YData
run("close all force; uf = uifigure('Position', [100 100 360 200]); g = uigridlayout(uf, [3 2]); ta = uitextarea(g); ta.Layout.Row = 3; ta.Layout.Column = [1 2]; "
    "lr = ta.Layout.Row; lc = ta.Layout.Column; tw = ta.Position(3); "
    "bf = figure('Visible', 'off'); bh = bar([1 2 3]); bh.YData(2) = 5; delete(uf); ")


def bar_tops(fig):
    """The laid-out tops of the first bar series in a figure, as the page gets them."""
    ser = serialize_figure(fig)
    t = [c for c in ser['axes'][0]['children'] if c.get('kind') == 'bar'][0]['top']
    if isinstance(t, dict) and '$' in t:
        import base64
        t = np.frombuffer(base64.b64decode(t['$']), {'f4': np.float32, 'f8': np.float64}[t['dt']])
    return np.round(np.asarray(t, float).reshape(-1), 4).tolist()


check("nested assignment into a handle's struct or array property: a grid child spans its columns, and the bars are laid out again",
      (val('lr'), np.asarray(val('lc')).reshape(-1).tolist(), val('tw') > 300, bar_tops(val('bf'))), (3, [1, 2], True, [1, 5, 3]))
run("close all force")

# a slider's, knob's and gauge's ticks follow Limits until they are set
run("uf = uifigure; s1 = uislider(uf, 'Limits', [0 10]); t1 = s1.MajorTicks; s2 = uislider(uf, 'MajorTicks', [0 50 100]); s2.Limits = [0 200]; t2 = s2.MajorTicks; "
    "gg = uigauge(uf, 'Limits', [-1 1]); t3 = gg.MajorTicks; delete(uf)")
check('ticks follow Limits (nice steps) until set by hand', (np.asarray(val('t1')).reshape(-1).tolist(), np.asarray(val('t2')).reshape(-1).tolist(), np.asarray(val('t3')).reshape(-1).tolist()),
      ([0, 2, 4, 6, 8, 10], [0, 50, 100], [-1, -0.5, 0, 0.5, 1]))

# a plotting function's name that a class also has (area of a polyshape) makes no figure when it gives a value
run("close all force; pg = polyshape([0 2 2 0], [0 0 2 2]); pa = area(pg); nf0 = numel(findall(groot, 'Type', 'figure')); area([1 2 3]); nf1 = numel(findall(groot, 'Type', 'figure')); close all force")
check('area of a polyshape is a number and makes no figure; the area chart still draws', (val('pa'), val('nf0'), val('nf1')), (4, 0, 1))

# optimplotx draws the point the solver ends at
run("close all force; po = optimoptions('fminunc', 'Display', 'off', 'PlotFcn', @optimplotx); px = fminunc(@(x) (x(1) - 1)^2 + (x(2) + 2)^2, [3 3], po); pf = gcf;")
check('optimplotx: the bars end at the solution', bar_tops(val('pf')), [1.0, -2.0])
run("close all force")

sys.exit(check.done())
