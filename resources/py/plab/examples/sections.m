%% Section 1: make some data
% Put the cursor in a section and press Ctrl+Enter (Cmd+Enter on a Mac)
% to run just that section.
x = 0:0.25:10;
y = exp(-x/4) .* cos(2*x);

%% Section 2: plot it
plot(x, y, 'o-')
title('A damped oscillation')

%% Section 3: fit a polynomial
p = polyfit(x, y, 6);
hold on
plot(x, polyval(p, x), 'LineWidth', 1.5)
hold off
legend('data', 'degree 6 fit')
