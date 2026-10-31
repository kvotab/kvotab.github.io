function mat_fixtures(outdir)
% The MATLAB-written MAT-files test-mat.py reads: a variable of each kind
% MATLAB saves, in the formats it saves them in. Written once with MATLAB
% R2023a into resources/tests/rb/fixtures; to write them again,
%
%     matlab -batch "mat_fixtures('<repository>/resources/tests/rb/fixtures')"
%
% run from a folder of no account, since a function handle keeps the path
% of the file it was made in.
d_mat = magic(4);
d_3d = reshape(1:24, 2, 3, 4);
d_empty = zeros(0, 3);
d_special = [NaN, Inf, -Inf, -0, 1e-310];
s_single = single([1.5 2.5; 3.5 4.5]);
i64 = int64([-9223372036854775807-1, 9223372036854775807]);
u8 = uint8([0 128 255]);
lg = [true false true; false true false];
cz = [1+2i, 3-4i; 5i, -6];
ch = 'hello';
ch_mat = ['abc'; 'def'];
ch_uni = 'Ångström µ ✓ δ';
ch_emoji = ['smile ' char([55357 56832])];
c_mixed = {1, 'two', [3 4 5]; {6}, struct('a', 1), []};
c_str = {'Ac-227', 'Am-241', 'Cs-135'};
c_long = arrayfun(@(k) 1:k, 1:12, 'UniformOutput', false);
c_table = {'Nuclide', 'Q'; 'Cs-135', 1.5; 'I-129', []};
c_nums = {1, [], 3};
s.a = 1;
s.b = 'text';
s.c.nested = magic(3);
sa(1).x = 1; sa(2).x = [1 2]; sa(3).x = 'three';
sa(1).y = 10; sa(2).y = 20; sa(3).y = 30;
sa(1).z = 'p'; sa(2).z = 'q'; sa(3).z = 'r';
sa(1).m = 1; sa(2).m = 'two'; sa(3).m = [];
s_empty = struct([]);
sp = sparse([1 0 0; 0 0 2; 3 0 0]);
sp_big = speye(1100);
fh = str2func('@(x) x.^2 + 1');
fh_named = @sin;
str_arr = ["alpha", "beta"; "gamma", "δέλτα"];
str_missing = [string(missing), "x", ""];
tbl = table([1; 2], {'a'; 'b'}, 'VariableNames', {'n', 'name'});
dt = datetime(2026, 10, 31, 12, 0, 0);
global gv
gv = 42;
vars = who;
vars = vars(~strcmp(vars, 'outdir'));
save(fullfile(outdir, 'matlab-v7.mat'), vars{:}, '-v7');
save(fullfile(outdir, 'matlab-v73.mat'), vars{:}, '-v7.3');
v4_mat = magic(3);
v4_char = ['ab'; 'cd'];
v4_cplx = [1+2i 3];
v4_sp = sparse([0 1; 2 0]);
save(fullfile(outdir, 'matlab-v4.mat'), 'v4_mat', 'v4_char', 'v4_cplx', 'v4_sp', '-v4');
end
