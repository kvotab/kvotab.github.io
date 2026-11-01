% Several lines in one axes, with a legend and labels.
t = linspace(0, 2*pi, 200);
plot(t, sin(t), 'LineWidth', 1.5)
hold on
plot(t, cos(t), '--', 'LineWidth', 1.5)
plot(t, sin(2*t) / 2, ':')
hold off
grid on
xlabel('t (rad)')
ylabel('amplitude')
title('Three waves')
legend('sin t', 'cos t', '0.5 sin 2t', 'Location', 'southwest')
