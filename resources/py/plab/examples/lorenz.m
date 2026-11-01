% The Lorenz system, solved with ode45 and drawn in three dimensions.
sigma = 10; rho = 28; beta = 8/3;
f = @(t, y) [sigma*(y(2) - y(1));
             y(1)*(rho - y(3)) - y(2);
             y(1)*y(2) - beta*y(3)];
[t, y] = ode45(f, [0 30], [1; 1; 1]);
plot3(y(:,1), y(:,2), y(:,3))
grid on
xlabel('x'), ylabel('y'), zlabel('z')
title(sprintf('Lorenz attractor, %d points', numel(t)))
view(-30, 20)
