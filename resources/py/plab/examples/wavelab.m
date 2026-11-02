function wavelab
%WAVELAB  A wave to play with: a small app made of figure controls.
%   wavelab opens a window with a plot and what changes it: the kind of
%   wave, its frequency (the slider, or the up and down arrow keys), its
%   amplitude and line style, markers, a menu, a toolbar and a context
%   menu in the plot. Play on the toolbar moves the wave with a timer;
%   a click in the plot tells where it is.
%
%   The callbacks are nested functions, so they share the variables of
%   wavelab: freq, amp, kind and the handles.

kinds = {'Sine', 'Cosine', 'Square', 'Sawtooth'};
kind = 1;
freq = 2;
amp = 1;
phase = 0;
x = linspace(0, 2*pi, 400);

fig = figure('Name', 'Wave lab', 'NumberTitle', 'off', 'MenuBar', 'none', ...
    'Position', [100 100 660 440], 'KeyPressFcn', @keys, 'CloseRequestFcn', @closing);

% the menus
fileMenu = uimenu(fig, 'Label', '&File');
uimenu(fileMenu, 'Label', 'Save picture...', 'Accelerator', 'E', 'Callback', @savePicture);
uimenu(fileMenu, 'Label', 'Close', 'Separator', 'on', 'Callback', @(~, ~) close(fig));
viewMenu = uimenu(fig, 'Label', '&View');
gridItem = uimenu(viewMenu, 'Label', 'Grid', 'Checked', 'on', 'Accelerator', 'G', 'Callback', @toggleGrid);

% the toolbar: play and reset
tools = uitoolbar(fig);
playTool = uitoggletool(tools, 'CData', icon('play'), 'TooltipString', 'Play', 'OnCallback', @play, 'OffCallback', @stopPlaying);
uipushtool(tools, 'CData', icon('reset'), 'TooltipString', 'Reset', 'ClickedCallback', @reset);

% the plot, in a panel
plotPanel = uipanel(fig, 'Title', 'The wave', 'Position', [0.31 0.03 0.67 0.95]);
ax = axes('Parent', plotPanel, 'Position', [0.12 0.12 0.83 0.8]);
waveLine = plot(ax, x, wave(), 'LineWidth', 1.5);
set(waveLine, 'HitTest', 'off')        % a click on the line is a click in the axes
axis(ax, [0 2*pi -2.2 2.2])
grid(ax, 'on')
xlabel(ax, 'x')
set(ax, 'ButtonDownFcn', @clicked)
colours = uicontextmenu(fig);
uimenu(colours, 'Label', 'Blue', 'Callback', @(~, ~) set(waveLine, 'Color', [0 0.447 0.741]));
uimenu(colours, 'Label', 'Red', 'Callback', @(~, ~) set(waveLine, 'Color', [0.85 0.2 0.1]));
uimenu(colours, 'Label', 'Green', 'Callback', @(~, ~) set(waveLine, 'Color', [0.2 0.6 0.2]));
set(ax, 'UIContextMenu', colours)

% the controls, on the left
uicontrol(fig, 'Style', 'text', 'String', 'Kind', 'HorizontalAlignment', 'left', 'Position', [16 382 160 18]);
kindMenu = uicontrol(fig, 'Style', 'popupmenu', 'String', kinds, 'Value', kind, 'Position', [16 358 170 24], 'Callback', @chooseKind);
uicontrol(fig, 'Style', 'text', 'String', 'Frequency', 'HorizontalAlignment', 'left', 'Position', [16 324 100 18]);
freqText = uicontrol(fig, 'Style', 'text', 'String', '', 'HorizontalAlignment', 'right', 'Position', [116 324 70 18]);
freqSlider = uicontrol(fig, 'Style', 'slider', 'Min', 1, 'Max', 10, 'Value', freq, 'SliderStep', [1 2] / 9, ...
    'Position', [16 302 170 20], 'Callback', @slide);
uicontrol(fig, 'Style', 'text', 'String', 'Amplitude', 'HorizontalAlignment', 'left', 'Position', [16 268 100 18]);
ampEdit = uicontrol(fig, 'Style', 'edit', 'String', num2str(amp), 'Position', [116 266 70 24], 'Callback', @setAmplitude);
styles = uibuttongroup(fig, 'Title', 'Line', 'Units', 'pixels', 'Position', [16 150 170 104], 'SelectionChangedFcn', @chooseStyle);
uicontrol(styles, 'Style', 'radiobutton', 'String', 'Solid', 'Tag', '-', 'Position', [10 58 140 20]);
uicontrol(styles, 'Style', 'radiobutton', 'String', 'Dashed', 'Tag', '--', 'Position', [10 34 140 20]);
uicontrol(styles, 'Style', 'radiobutton', 'String', 'Dotted', 'Tag', ':', 'Position', [10 10 140 20]);
markers = uicontrol(fig, 'Style', 'checkbox', 'String', 'Markers', 'Position', [16 118 170 22], 'Callback', @toggleMarkers);
readout = uicontrol(fig, 'Style', 'text', 'String', 'Click in the plot.', 'HorizontalAlignment', 'left', 'Position', [16 52 170 52]);

ticker = timer('Period', 0.1, 'ExecutionMode', 'fixedRate', 'TimerFcn', @step);
redraw()

    function y = wave()
        t = freq * x + phase;
        switch kind
            case 1
                y = amp * sin(t);
            case 2
                y = amp * cos(t);
            case 3
                y = amp * sign(sin(t));
            otherwise
                y = amp * (mod(t, 2*pi) / pi - 1);
        end
    end

    function redraw()
        set(waveLine, 'YData', wave())
        set(freqText, 'String', sprintf('%g', freq))
        title(ax, sprintf('%s, frequency %g, amplitude %g', kinds{kind}, freq, amp))
    end

    function chooseKind(src, ~)
        kind = get(src, 'Value');
        redraw()
    end

    function slide(src, ~)
        freq = round(get(src, 'Value'));
        set(src, 'Value', freq)
        redraw()
    end

    function setAmplitude(src, ~)
        a = str2double(get(src, 'String'));
        if isnan(a) || a <= 0 || a > 2
            errordlg('The amplitude is a number above 0 and at most 2.', 'Wave lab')
            set(src, 'String', num2str(amp))
            return
        end
        amp = a;
        redraw()
    end

    function chooseStyle(~, event)
        set(waveLine, 'LineStyle', get(event.NewValue, 'Tag'))
    end

    function toggleMarkers(src, ~)
        if get(src, 'Value')
            set(waveLine, 'Marker', 'o', 'MarkerIndices', 1:20:numel(x), 'MarkerSize', 5)
        else
            set(waveLine, 'Marker', 'none')
        end
    end

    function toggleGrid(src, ~)
        if strcmp(get(src, 'Checked'), 'on')
            set(src, 'Checked', 'off')
            grid(ax, 'off')
        else
            set(src, 'Checked', 'on')
            grid(ax, 'on')
        end
    end

    function clicked(~, ~)
        p = get(ax, 'CurrentPoint');
        set(readout, 'String', {sprintf('x = %.3f', p(1, 1)), sprintf('y = %.3f', p(1, 2))})
    end

    function keys(~, event)
        switch event.Key
            case 'uparrow'
                freq = min(freq + 1, 10);
            case 'downarrow'
                freq = max(freq - 1, 1);
            otherwise
                return
        end
        set(freqSlider, 'Value', freq)
        redraw()
    end

    function step(~, ~)
        phase = phase - 0.25;
        redraw()
    end

    function play(~, ~)
        start(ticker)
    end

    function stopPlaying(~, ~)
        stop(ticker)
    end

    function reset(~, ~)
        set(playTool, 'State', 'off')
        stop(ticker)
        phase = 0;
        freq = 2;
        amp = 1;
        set(freqSlider, 'Value', freq)
        set(ampEdit, 'String', num2str(amp))
        redraw()
    end

    function savePicture(~, ~)
        [name, folder] = uiputfile({'*.png', 'PNG picture (*.png)'}, 'Save the plot', 'wave.png');
        if ~isequal(name, 0)
            saveas(fig, fullfile(folder, name))
        end
    end

    function closing(~, ~)
        stop(ticker)
        delete(ticker)
        delete(fig)
    end
end

function c = icon(which)
% 16 x 16 pictures for the toolbar: NaN shows the toolbar through.
c = nan(16, 16, 3);
[col, row] = meshgrid(1:16, 1:16);
switch which
    case 'play'
        on = col >= 5 & col <= 12 & abs(row - 8.5) <= (12 - col) * 0.55 + 0.5;
        ink = [0.15 0.5 0.2];
    otherwise
        r = hypot(col - 8.5, row - 8.5);
        on = r >= 4 & r <= 6.2 & ~(col > 8.5 & row < 8);
        on(2:5, 9:12) = (row(2:5, 9:12) - 1) >= (col(2:5, 9:12) - 9) & (row(2:5, 9:12) - 1) <= (13 - col(2:5, 9:12));
        ink = [0.2 0.25 0.45];
end
for k = 1:3
    layer = c(:, :, k);
    layer(on) = ink(k);
    c(:, :, k) = layer;
end
end
