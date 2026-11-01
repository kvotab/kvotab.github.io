function steps = collatz(n)
%COLLATZ  Number of steps for n to reach 1 in the 3n+1 sequence.
%   steps = collatz(n) counts the steps; collatz(n) with no output
%   also plots the sequence.
%
%   Example:  collatz(27)
if n < 1 || n ~= fix(n)
    error('collatz:badInput', 'n must be a positive whole number, not %g.', n);
end
seq = n;
while seq(end) ~= 1
    seq(end+1) = next_term(seq(end)); %#ok<AGROW>
end
steps = numel(seq) - 1;
if nargout == 0
    plot(0:steps, seq, '.-')
    xlabel('step'), ylabel('value')
    title(sprintf('Collatz sequence from %d (%d steps)', n, steps))
    clear steps
end
end

function m = next_term(k)
if mod(k, 2) == 0
    m = k / 2;
else
    m = 3*k + 1;
end
end
