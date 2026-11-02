function fig_fixtures(outdir)
% The MATLAB-written figure files test-fig.py reads: figures of the kinds
% the HDF5 Browser draws, saved by savefig. Written once with MATLAB R2023a
% into resources/tests/rb/fixtures; to write them again,
%
%     matlab -batch "fig_fixtures('<repository>/resources/tests/rb/fixtures')"
%
% run from a folder of no account: a figure keeps the name of the file it
% was saved to, and test-fig.py checks that no fixture keeps a home folder.
set(groot, 'DefaultFigureVisible', 'off');
x = linspace(0, 2*pi, 50);

% Lines, a legend, labels read as TeX, a grid and a text.
f = figure('Position', [100 100 640 480], 'Name', 'Waves');
plot(x, sin(x), x, cos(x), '--o', 'LineWidth', 1.5);
hold on;
plot(x, 0.5*sin(2*x), 'r:', 'DisplayName', 'half');
title('Waves \alpha^2 and x_{i}');
xlabel('Time (s)');
ylabel('Amplitude \muSv');
legend('sin', 'cos', 'half', 'Location', 'southwest');
grid on;
text(pi, 0.5, 'peak \rightarrow', 'Color', 'b');
xlim([0 2*pi]);
savefig(f, fullfile(outdir, 'figure-plot.fig'));
close(f);

% A subplot of each kind of object: bars, log axes, a surface in 3-D with a
% colour bar, an image, filled contours and a pie.
f = figure;
subplot(2, 3, 1); bar([1 2 3; 4 5 6]); title('bar'); legend('a', 'b', 'c');
subplot(2, 3, 2); loglog(logspace(0, 5, 20), logspace(0, 5, 20).^2, 'k-s'); grid on; title('loglog');
subplot(2, 3, 3); surf(peaks(12)); colorbar; title('surf');
subplot(2, 3, 4); imagesc(magic(6)); colorbar; title('imagesc');
subplot(2, 3, 5); contourf(peaks(20), 6); title('contourf');
subplot(2, 3, 6); pie([1 2 3]);
savefig(f, fullfile(outdir, 'figure-kinds.fig'));
close(f);

% A window of controls, as GUIDE lays one out, in characters.
f = figure('Name', 'Controls', 'MenuBar', 'none', 'Units', 'characters', 'Position', [10 10 80 20]);
uicontrol(f, 'Style', 'pushbutton', 'String', 'Run', 'Units', 'characters', 'Position', [2 2 15 2]);
uicontrol(f, 'Style', 'edit', 'String', '0.5', 'Units', 'characters', 'Position', [20 2 15 2]);
uicontrol(f, 'Style', 'popupmenu', 'String', {'one', 'two'}, 'Units', 'characters', 'Position', [40 2 15 2]);
uicontrol(f, 'Style', 'checkbox', 'String', 'Check', 'Value', 1, 'Units', 'characters', 'Position', [2 6 15 2]);
uicontrol(f, 'Style', 'listbox', 'String', {'a', 'b', 'c'}, 'Units', 'characters', 'Position', [20 6 15 5]);
uicontrol(f, 'Style', 'slider', 'Value', 0.3, 'Units', 'characters', 'Position', [40 6 20 1.5]);
p = uipanel(f, 'Title', 'Panel', 'Units', 'characters', 'Position', [40 10 35 9]);
uicontrol(p, 'Style', 'radiobutton', 'String', 'Radio', 'Units', 'characters', 'Position', [2 2 15 2]);
uimenu(f, 'Label', '&File');
savefig(f, fullfile(outdir, 'figure-controls.fig'));
close(f);

% Two figures in one file.
f1 = figure; plot(1:3, [2 1 3]);
f2 = figure; bar([3 1 2]);
savefig([f1 f2], fullfile(outdir, 'figure-two.fig'));
close all;

% A figure saved in R2014b's form alone, and one whose objects only that
% form keeps.
f = figure; plot(1:5);
savefig(f, fullfile(outdir, 'figure-compact.fig'), 'compact');
close(f);
f = figure; t = tiledlayout(f, 1, 2); nexttile(t); plot(1:4); nexttile(t); plot(4:-1:1);
savefig(f, fullfile(outdir, 'figure-tiled.fig'));
close(f);
end
