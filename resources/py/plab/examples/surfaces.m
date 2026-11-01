% A surface, its contours and a filled contour plot.
[X, Y] = meshgrid(linspace(-3, 3, 40));
Z = X .* exp(-X.^2 - Y.^2) + 0.2 * sin(2*Y);

subplot(1, 2, 1)
surf(X, Y, Z)
shading interp
title('surf')
xlabel('x'), ylabel('y'), zlabel('z')

subplot(1, 2, 2)
contourf(X, Y, Z, 12)
colorbar
axis equal tight
title('contourf')
