% Random numbers, a histogram and summary statistics.
rng(1)
x = 10 + 2*randn(1, 2000);
histogram(x, 'Normalization', 'pdf')
hold on
t = linspace(min(x), max(x), 200);
plot(t, exp(-(t - 10).^2 / 8) / sqrt(8*pi), 'LineWidth', 2)
hold off
title('2000 draws from N(10, 2^2)')
fprintf('mean %.3f, std %.3f, median %.3f\n', mean(x), std(x), median(x));
