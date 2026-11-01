% An animation: drawnow shows each frame as the loop runs.
% Press Ctrl+C in the Command Window to stop it early.
theta = linspace(0, 8*pi, 400);
h = plot(NaN, NaN, 'LineWidth', 1.5);
axis([-1 1 -1 1] * 1.1)
axis square
grid on
for k = 5:5:numel(theta)
    r = theta(1:k) / theta(end);
    set(h, 'XData', r .* cos(theta(1:k)), 'YData', r .* sin(theta(1:k)))
    title(sprintf('Frame %d', k/5))
    drawnow
    pause(0.02)
end
