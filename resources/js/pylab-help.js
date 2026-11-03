/* ==========================================================================
   PYLAB.HTML: HELP

   The Help tab: how the desktop works, its keys, what the language covers
   here, and every function by category (a click shows its help).
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { el } = PL;

  const CATEGORIES = [
    ['The language', 'if elseif else for while switch case otherwise try catch function end break continue return global persistent classdef'],
    ['Making arrays', 'zeros ones eye rand randn randi randperm rng linspace logspace colon magic diag repmat repelem bsxfun reshape cat horzcat vertcat meshgrid ndgrid true false pi eps Inf NaN i j intmax intmin realmax realmin flintmax blkdiag toeplitz hankel vander hilb invhilb pascal compan wilkinson rosser accumarray'],
    ['Size and shape', 'size numel length ndims isempty isscalar isvector isrow iscolumn ismatrix issquare squeeze permute ipermute shiftdim circshift flip fliplr flipud rot90 tril triu kron sub2ind ind2sub find nnz nonzeros'],
    ['Arithmetic', 'plus minus times rdivide ldivide mtimes mrdivide mldivide power mpower uminus uplus transpose ctranspose abs sign sqrt nthroot hypot exp expm1 log log1p log2 log10 pow2 nextpow2 reallog realpow realsqrt floor ceil round fix mod rem idivide bitand bitor bitxor bitshift bitcmp bitget bitset gcd lcm factorial nchoosek primes isprime factor perms rat rats'],
    ['Trigonometry', 'sin cos tan sec csc cot asin acos atan atan2 asec acsc acot sinh cosh tanh sech csch coth asinh acosh atanh asech acsch acoth sind cosd tand secd cscd cotd asind acosd atand asecd acscd acotd atan2d sinpi cospi deg2rad rad2deg'],
    ['Complex numbers', 'real imag conj angle complex isreal cplxpair unwrap cart2pol pol2cart cart2sph sph2cart'],
    ['Comparison and logic', 'eq ne lt gt le ge and or not xor any all isequal isequaln isnan ismissing isinf isfinite'],
    ['Data analysis', 'sum prod cumsum cumprod cummax cummin diff mean median mode std var min max bounds range sort sortrows issorted unique ismember union intersect setdiff setxor histcounts histcounts2 histc discretize cov corrcoef trapz cumtrapz quantile prctile iqr skewness kurtosis movmean movsum movprod movmax movmin movmedian movmad movstd movvar rescale normalize'],
    ['Descriptive statistics', 'trimmean geomean harmmean mad rms moment zscore nanmean nanmedian nanstd nanvar nansum nanmax nanmin tabulate grp2idx grpstats ecdf ksdensity corr bootstrp jackknife'],
    ['Probability distributions', 'makedist fitdist mle pdf cdf icdf random truncate paramci negloglik normfit unifit binofit mvnpdf mvncdf mvnrnd mvtpdf mvtcdf mvtrnd randsample datasample normpdf normcdf norminv normrnd normstat normlike lognpdf logncdf logninv lognrnd lognstat lognfit lognlike exppdf expcdf expinv exprnd expstat expfit explike gampdf gamcdf gaminv gamrnd gamstat gamfit gamlike betapdf betacdf betainv betarnd betastat betafit betalike wblpdf wblcdf wblinv wblrnd wblstat wblfit wbllike unifpdf unifcdf unifinv unifrnd unifstat unidpdf unidcdf unidinv unidrnd unidstat binopdf binocdf binoinv binornd binostat poisspdf poisscdf poissinv poissrnd poissstat poissfit geopdf geocdf geoinv geornd geostat nbinpdf nbincdf nbininv nbinrnd nbinstat nbinfit nbinlike hygepdf hygecdf hygeinv hygernd hygestat chi2pdf chi2cdf chi2inv chi2rnd chi2stat ncx2pdf ncx2cdf ncx2inv ncx2rnd ncx2stat tpdf tcdf tinv trnd tstat nctpdf nctcdf nctinv nctrnd nctstat fpdf fcdf finv frnd fstat ncfpdf ncfcdf ncfinv ncfrnd ncfstat evpdf evcdf evinv evrnd evstat evfit evlike gevpdf gevcdf gevinv gevrnd gevstat gevfit gevlike gppdf gpcdf gpinv gprnd gpstat gpfit gplike raylpdf raylcdf raylinv raylrnd raylstat raylfit'],
    ['Hypothesis tests', 'ttest ttest2 ztest vartest vartest2 vartestn signtest signrank ranksum kstest kstest2 lillietest jbtest adtest chi2gof runstest anova1 anova2 kruskalwallis friedman multcompare crosstab fishertest'],
    ['Linear algebra', 'inv det trace rank norm vecnorm cond rcond condest eig eigs svd svds qr lu chol schur hess pinv null orth rref expm logm sqrtm funm cross dot linsolve balance issymmetric ishermitian istril istriu isbanded bandwidth pcg bicg bicgstab cgs gmres minres qmr tfqmr lsqr cholupdate qrupdate qrinsert qrdelete qz ordschur ordeig polyeig givens planerot isdiag'],
    ['Sparse matrices', 'sparse full issparse nzmax spalloc speye spones sprand sprandn spzeros spdiags spfun'],
    ['Special functions', 'gamma gammaln gammainc gammaincinv beta betaln betainc betaincinv erf erfc erfinv erfcinv erfcx expint psi besselj bessely besseli besselk besselh airy ellipke ellipj legendre'],
    ['Polynomials, filters and transforms', 'polyfit polyval polyvalm roots poly conv deconv polyder polyint residue filter filter2 conv2 convn fft ifft fft2 ifft2 fftn ifftn fftshift ifftshift detrend gradient del2'],
    ['Interpolation', 'interp1 interp2 interp3 interpn griddata griddedInterpolant scatteredInterpolant spline pchip makima ppval mkpp unmkpp'],
    ['Optimization', 'fzero fminbnd fminsearch fminunc fmincon fsolve lsqnonlin lsqcurvefit lsqlin lsqnonneg linprog intlinprog quadprog fminimax fgoalattain optimoptions resetoptions optimset optimget optimplotfval optimplotx optimplotfirstorderopt optimplotfunccount optimplotconstrviolation optimplotstepsize optimplotresnorm'],
    ['Apps', 'appdesigner uifigure uibutton uilabel uieditfield uitextarea uidropdown uilistbox uicheckbox uiswitch uislider uispinner uiknob uigauge uilamp uiradiobutton uitogglebutton uiimage uihyperlink uigridlayout uiaxes uialert uiconfirm uiprogressdlg createCallbackFcn registerApp runStartupFcn'],
    ['Classes', 'classdef properties methods ismethod isprop isobject isvalid addlistener listener notify'],
    ['Mapping', 'deg2km km2deg deg2nm nm2deg deg2sm sm2deg km2nm nm2km km2sm sm2km nm2sm sm2nm km2rad rad2km unitsratio dms2degrees degrees2dms dm2degrees degrees2dm wrapTo180 wrapTo360 wrapToPi wrapTo2Pi referenceEllipsoid wgs84Ellipsoid referenceSphere earthRadius distance azimuth reckon track1 track2 gcwaypts meridianarc antipode areaint areaquad interpm geodetic2ecef ecef2geodetic geodetic2enu enu2geodetic geodetic2ned ned2geodetic geodetic2aer aer2geodetic ecef2enu enu2ecef ecef2ned ned2ecef ecef2aer aer2ecef enu2aer aer2enu ned2aer aer2ned inpolygon polyarea ispolycw poly2cw poly2ccw polysplit polyjoin polyxpoly projcrs geocrs projfwd projinv axesm worldmap setm getm gcm defaultm ismap framem gridm mlabel plabel tightmap showaxes mfwdtran minvtran plotm linem scatterm textm patchm fillm surfm pcolorm contourm geoshow mapshow geoaxes geoplot geoscatter geobubble geolimits geobasemap addCustomBasemap removeCustomBasemap georefcells georefpostings georasterref maprefcells maprefpostings geographicToIntrinsic worldToIntrinsic geointerp shaperead shapeinfo shapewrite readgeoraster geotiffread geotiffinfo'],
    ['Symbolic math', 'sym syms str2sym symfun argnames formula vpa digits subs simplify simplifyFraction expand factor collect combine horner rewrite partfrac numden coeffs poly2sym sym2poly children has lhs rhs isolate finverse compose diff int limit taylor series symsum symprod jacobian hessian gradient divergence curl laplacian solve vpasolve dsolve laplace ilaplace fourier ifourier ztrans iztrans assume assumeAlso assumptions isAlways piecewise heaviside dirac kroneckerDelta sinc lambertw zeta latex pretty char double matlabFunction fplot fimplicit fplot3 fsurf'],
    ['Integration', 'integral integral2 integral3 quadgk quad quadl quad2d dblquad triplequad'],
    ['Differential equations', 'ode45 ode23 ode113 ode78 ode89 ode15s ode23s ode23t ode23tb ode15i decic odeset odeget odeplot deval odextend'],
    ['Text', 'char string strings cellstr sprintf num2str int2str mat2str str2num str2double strcat strvcat strjoin strsplit split join splitlines strtrim strip deblank blanks pad strjust upper lower reverse strlength strcmp strcmpi strncmp strncmpi contains startsWith endsWith matches strfind strmatch count strtok strrep replace erase extractBefore extractAfter extractBetween replaceBetween eraseBetween insertAfter insertBefore regexp regexpi regexprep regexptranslate isspace isletter isstrprop istext dec2bin bin2dec dec2hex hex2dec dec2base base2dec num2hex hex2num compose newline sscanf validatestring convertCharsToStrings convertStringsToChars'],
    ['Cells, structs and maps', 'cell cellfun num2cell cell2mat mat2cell celldisp cell2struct struct2cell struct fieldnames isfield rmfield setfield getfield orderfields arrayfun structfun containers.Map keys values isKey remove deal iscell iscellstr isstruct'],
    ['Types', 'class isa isnumeric isfloat isinteger islogical ischar isstring isobject double single int8 uint8 int16 uint16 int32 uint32 int64 uint64 logical cast typecast swapbytes func2str str2func symvar feval functions'],
    ['Parallel loops', 'parfor parpool gcp getCurrentTask spmd'],
    ['Programs and the workspace', 'disp display fprintf input keyboard error warning lasterr lastwarn MException throw rethrow throwAsCaller addCause getReport assert onCleanup exist clear clearvars who whos eval evalin evalc assignin inputname mfilename nargin nargout narginchk nargoutchk validateattributes isvarname iskeyword genvarname matlab.lang.makeValidName matlab.lang.makeUniqueStrings namelengthmax builtin format clc more echo diary beep sound soundsc profile help version ver computer ispc ismac isunix isdeployed usejava matlabroot userpath getenv setenv web exit quit'],
    ['Missing data and outliers', 'ismissing fillmissing rmmissing standardizeMissing isoutlier filloutliers smoothdata findgroups splitapply'],
    ['Checking arguments', 'validateattributes validatestring inputParser addRequired addOptional addParameter addParamValue parse narginchk nargoutchk nargchk mustBePositive mustBeNonnegative mustBeNegative mustBeNonpositive mustBeNonzero mustBeInteger mustBeNumeric mustBeNumericOrLogical mustBeFloat mustBeReal mustBeFinite mustBeNonNan mustBeNonempty mustBeNonsparse mustBeGreaterThan mustBeGreaterThanOrEqual mustBeLessThan mustBeLessThanOrEqual mustBeInRange mustBeMember mustBeText mustBeTextScalar mustBeNonzeroLengthText mustBeVector mustBeScalarOrEmpty mustBeA mustBeUnderlyingType mustBeNonmissing mustBeValidVariableName mustBeFile mustBeFolder'],
    ['Geometry', 'delaunay convhull voronoi voronoin tsearchn dsearchn inpolygon polyarea rectint triplot trisurf trimesh'],
    ['Images, sound and the web', 'imread imwrite imfinfo image imagesc audioread audiowrite audioinfo sound soundsc webread webwrite websave weboptions web'],
    ['Dates and time', 'tic toc pause cputime clock now date datenum datestr datevec etime weekday eomday addtodate leapyear'],
    ['Files and folders', 'pwd cd dir ls what which type edit open run mkdir rmdir delete copyfile movefile zip unzip gzip gunzip tar untar fullfile fileparts filesep pathsep tempdir tempname isfile isfolder isdir addpath rmpath path genpath rehash fopen fclose fgetl fgets fread fwrite fprintf fscanf feof ferror frewind ftell fseek fileread readlines writelines textscan textread readmatrix jsondecode jsonencode writematrix csvread csvwrite dlmread dlmwrite readcell writecell load save matfile importdata'],
    ['Line and area plots', 'plot plot3 line semilogx semilogy loglog fplot ezplot scatter scatter3 bubblechart bubblechart3 bubblesize bubblelim bar barh histogram hist area fill fill3 patch stairs stem errorbar pie polarplot polarscatter polarbubblechart polaraxes polar quiver quiver3 compass feather rose pareto stem3 comet comet3 bar3 bar3h histogram2 pie3 ribbon'],
    ['Statistical plots', 'boxplot gscatter gplotmatrix plotmatrix scatterhist histfit normplot qqplot cdfplot lsline refline refcurve'],
    ['Surfaces, contours and images', 'contour contourf contour3 contourc clabel fcontour ezcontour surf surfc surfl mesh meshc meshz waterfall pcolor surface fsurf fmesh ezsurf ezmesh image imagesc imshow peaks sphere cylinder ellipsoid shading view camzoom camva light camlight lighting material colorbar colormap clim caxis alpha hidden isosurface slice stream2 stream3 streamline'],
    ['Figures and axes', 'figure clf close gcf gca gco groot axes polaraxes cla subplot tiledlayout nexttile hold ishold newplot axis xlim ylim zlim xticks yticks zticks xticklabels yticklabels zticklabels xtickangle ytickangle grid box daspect pbaspect yyaxis colororder title subtitle sgtitle suptitle xlabel ylabel zlabel legend text annotation set get findobj findall allchild ancestor copyobj gobjects ishandle ishghandle isgraphics isvalid isprop drawnow refresh shg getframe frame2im im2frame movie saveas exportgraphics print savefig openfig hgsave hgload ginput waitforbuttonpress zoom pan rotate3d datacursormode brush linkaxes linkprop whitebg camorbit campos'],
    ['User interfaces', 'uicontrol uipanel uibuttongroup uitable uitabgroup uitab uimenu uicontextmenu uitoolbar uipushtool uitoggletool gcbo gcbf closereq uiwait uiresume waitfor guidata setappdata getappdata isappdata rmappdata msgbox errordlg warndlg helpdlg questdlg inputdlg listdlg menu uigetfile uiputfile uigetdir uisetcolor waitbar dialog printdlg printpreview helpwin doc timer start stop wait timerfind timerfindall movegui uistack'],
    ['Colormaps', 'parula viridis turbo jet gray hot cool spring summer autumn winter bone copper pink hsv lines prism flag white colorcube'],
  ];

  class HelpView {
    constructor(app) {
      this.app = app;
      this.el = el('div', { class: 'pl-help' });
      this.home();
    }

    home() {
      const k = PL.util.modName;
      const search = el('input', { type: 'search', placeholder: 'Find a function', 'aria-label': 'Find a function' });
      search.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && search.value.trim()) this.show(search.value.trim()); });
      const lists = CATEGORIES.map(([title, names]) => {
        const list = el('div', { class: 'pl-fnlist' });
        for (const n of names.split(' ')) {
          const a = el('a', { href: '#', 'data-fn': n }, n);
          a.addEventListener('click', (ev) => { ev.preventDefault(); this.show(n); });
          list.append(a);
        }
        return [el('h3', null, title), list];
      });
      this.el.replaceChildren(
        el('h2', null, 'PyLAB'),
        el('p', null, 'A desktop for programs in the MATLAB language. What you type in the Command Window and the files you run from the Editor are compiled to Python and run on NumPy and SciPy, in this browser tab (Pyodide). Nothing is sent to a server; your files are kept in this browser.'),
        el('p', null, search),
        el('h3', null, 'Getting started'),
        el('ul', null,
          el('li', null, 'Type a command at ', el('code', null, '>>'), ' and press Enter. End it with ', el('code', null, ';'), ' to run it without showing the result.'),
          el('li', null, 'An unfinished block (', el('code', null, 'for'), ', ', el('code', null, 'if'), ', ', el('code', null, 'function'), '…) or bracket takes another line; Shift+Enter starts a new line yourself.'),
          el('li', null, 'Up and Down recall earlier commands (those starting with what you typed); Tab completes names; Ctrl+C stops a running program.'),
          el('li', null, 'New Script opens the Editor. Save with ', el('code', null, `${k}S`), ', run with F5, run the section under the cursor with ', el('code', null, `${k}Enter`), ' and the selection with F9.'),
          el('li', null, 'Click in the Editor’s margin (or press F12) for a breakpoint. When a run stops there, the prompt reads ', el('code', null, 'K>>'), ': look at and change the variables, then Step (F10), Step In (F11), Step Out (Shift+F11) or Continue (F5).'),
          el('li', null, 'Drop files from your computer anywhere on the desktop: they are copied into the current folder, programs and text open in the Editor and MAT-files load into the workspace. Dropped on the Current Folder they are only copied (on a folder in it, into that folder). A folder dropped is copied with its files.'),
          el('li', null, 'The Current Folder lists your files; right-click a file to download it.'),
          el('li', null, 'Double-click a variable in the Workspace to see it as a table. Select variables and pick a chart in the PLOTS tab.'),
          el('li', null, 'Figures open in windows of their own. In a figure, drag to pan (or to turn a 3-D view), scroll to zoom, double-click to go back; the toolbar has zoom by box, data tips and saving as a picture.'),
          el('li', null, 'Programs can make windows of their own, with controls, menus, toolbars, context menus and dialogs (uicontrol, uimenu, msgbox and the rest under User interfaces); their callbacks run when someone uses them. ',
            el('code', null, 'examples/wavelab.m'), ' is one.'),
          el('li', null, 'View Python in the EDITOR tab shows the Python a file compiles to.')),
        el('h3', null, 'Keys'),
        keysTable(k),
        el('h3', null, 'The language here'),
        el('ul', null,
          el('li', null, 'Scripts, functions with local and nested functions, anonymous functions and handles, cell arrays, structs and struct arrays, string arrays, integer and single types, logical indexing, ', el('code', null, 'end'), ' in indices, implicit expansion, comma-separated lists, varargin and varargout, global and persistent variables, try/catch with error identifiers, and ', el('code', null, 'containers.Map'), '.'),
          el('li', null, 'Not here: classdef files (classes of your own), Simulink, the toolboxes beyond the functions listed below, Java, MEX files, and App Designer apps (uifigure and .mlapp files). Sparse matrices are held as full ones.'),
          el('li', null, 'Numbers are IEEE doubles, as NumPy and SciPy compute them; random numbers come from a Mersenne Twister, and rand with the default seed gives the usual first numbers.'),
          el('li', null, 'Statistics: probability distributions (their functions, fits and distribution objects), descriptive statistics, hypothesis tests and statistical plots, computed with SciPy. The lists below have them all.'),
          el('li', null, 'MAT-files of versions 4 to 7 load and save; version 7.3 files load.')),
        el('h3', null, 'Functions'),
        ...lists.flat(),
        el('p', { class: 'pl-notice' }, 'MATLAB is a registered trademark of The MathWorks, Inc. PyLAB is not made by The MathWorks and is not affiliated with or endorsed by it; it runs programs written in the same language.'),
      );
      this.el.scrollTop = 0;
    }

    async show(name) {
      let h;
      try { h = await PL.engine.call('help_text', name); } catch (e) { h = { text: `${name}: ${e.message}` }; }
      const back = el('button', { class: 'pl-btn', type: 'button' }, '← All functions');
      back.addEventListener('click', () => this.home());
      const pre = el('pre');
      pre.textContent = h.base || h.text;
      const parts = [back, el('h2', null, name), pre];
      // how PyLAB computes it, as paragraphs (the Command Window has them wrapped into its text)
      if (h.how && h.how.length) {
        const how = el('section', { class: 'pl-how' }, el('h3', null, 'How it works'));
        for (const b of h.how) how.append(b.pre !== undefined ? el('pre', null, b.pre) : el('p', null, b.p));
        parts.push(how);
      }
      if (h.kind === 'file') {
        const open = el('button', { class: 'pl-btn', type: 'button' }, 'Open in the Editor');
        open.addEventListener('click', () => this.app.openFile(h.path));
        parts.push(open);
      }
      this.el.replaceChildren(...parts);
      this.el.scrollTop = 0;
    }
  }

  function keysTable(k) {
    const rows = [
      ['Enter', 'run the command (or go on to another line in an open block)'], ['Shift+Enter', 'a new line in the Command Window'],
      ['Up / Down', 'earlier commands'], ['Tab', 'complete a name'], ['Ctrl+C', 'stop the running program'], ['Escape', 'clear the command line'],
      ['F5', 'run the file (Continue when stopped)'], [`${k}Enter`, 'run the section'], ['F9', 'run the selection'], [`${k}S`, 'save'],
      ['F12', 'breakpoint on or off'], ['F10 / F11 / Shift+F11', 'step, step in, step out'], [`${k}/`, 'comment lines out or in'],
      [`${k}I`, 'indent the selection by its blocks'], [`${k}F`, 'find and replace'], [`${k}G`, 'go to a line'],
      [`${k}0`, 'the Command Window'], [`${k}Shift+0`, 'the Editor'],
    ];
    const t = el('table', { class: 'pl-table', style: { maxWidth: '640px' } });
    const b = el('tbody');
    for (const [a, d] of rows) b.append(el('tr', null, el('td', { class: 'pl-mono', style: { width: '38%' } }, a), el('td', { style: { whiteSpace: 'normal' } }, d)));
    t.append(b);
    return t;
  }

  PL.HelpView = HelpView;
  PL.helpCategories = CATEGORIES;
})(window);
