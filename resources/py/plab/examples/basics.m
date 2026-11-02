%% Basics: numbers, matrices and indexing
a = 3;
b = a^2 + 1
v = linspace(0, 1, 5)
M = magic(4)
M(2, :)            % the second row
M(end, end)        % the last element
M(M > 10)'         % elements above 10, as a row

%% Strings, cells and structs
name = 'PyLAB';
msg = sprintf('%s has %d letters', name, numel(name))
words = strsplit('alpha beta gamma', ' ')
s.title = 'Results';
s.values = [1.5 2.5 3.5];
s
fprintf('Mean of the values: %.3f\n', mean(s.values));
