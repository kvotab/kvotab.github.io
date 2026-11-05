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
    ['Making arrays', 'zeros ones eye rand randn randi randperm rng linspace logspace colon magic diag repmat repelem bsxfun reshape cat horzcat vertcat meshgrid ndgrid true false pi eps Inf NaN i j intmax intmin realmax realmin flintmax blkdiag toeplitz hankel vander hilb invhilb pascal compan wilkinson rosser accumarray inf nan'],
    ['Size and shape', 'size numel length ndims isempty isscalar isvector isrow iscolumn ismatrix issquare squeeze permute ipermute shiftdim circshift flip fliplr flipud rot90 tril triu kron pagemtimes pagetranspose pagectranspose tensorprod sub2ind ind2sub find nnz nonzeros'],
    ['Arithmetic', 'plus minus times rdivide ldivide mtimes mrdivide mldivide power mpower uminus uplus transpose ctranspose abs sign sqrt nthroot hypot exp expm1 log log1p log2 log10 pow2 nextpow2 reallog realpow realsqrt floor ceil round fix mod rem idivide bitand bitor bitxor bitshift bitcmp bitget bitset gcd lcm factorial nchoosek primes isprime factor perms rat rats cbrt'],
    ['Trigonometry', 'sin cos tan sec csc cot asin acos atan atan2 asec acsc acot sinh cosh tanh sech csch coth asinh acosh atanh asech acsch acoth sind cosd tand secd cscd cotd asind acosd atand asecd acscd acotd atan2d sinpi cospi deg2rad rad2deg'],
    ['Complex numbers', 'real imag conj angle complex isreal cplxpair unwrap cart2pol pol2cart cart2sph sph2cart'],
    ['Comparison and logic', 'eq ne lt gt le ge and or not xor any all isequal isequaln isnan ismissing isinf isfinite'],
    ['Data analysis', 'sum prod cumsum cumprod cummax cummin diff mean median mode std var min max bounds range sort sortrows issorted unique ismember union intersect setdiff setxor histcounts histcounts2 histc discretize cov corrcoef trapz cumtrapz quantile prctile iqr skewness kurtosis movmean movsum movprod movmax movmin movmedian movmad movstd movvar rescale normalize islocalmax islocalmin ischange trenddecomp mink maxk clip allfinite anynan isuniform resize paddata trimdata uniquetol ismembertol rmse mape'],
    ['Descriptive statistics', 'trimmean geomean harmmean mad rms moment zscore nanmean nanmedian nanstd nanvar nansum nanmax nanmin tabulate grp2idx grpstats ecdf ksdensity corr bootstrp jackknife'],
    ['Probability distributions', 'makedist fitdist mle pdf cdf icdf random truncate paramci negloglik normfit unifit binofit mvnpdf mvncdf mvnrnd mvtpdf mvtcdf mvtrnd randsample datasample normpdf normcdf norminv normrnd normstat normlike lognpdf logncdf logninv lognrnd lognstat lognfit lognlike exppdf expcdf expinv exprnd expstat expfit explike gampdf gamcdf gaminv gamrnd gamstat gamfit gamlike betapdf betacdf betainv betarnd betastat betafit betalike wblpdf wblcdf wblinv wblrnd wblstat wblfit wbllike unifpdf unifcdf unifinv unifrnd unifstat unidpdf unidcdf unidinv unidrnd unidstat binopdf binocdf binoinv binornd binostat poisspdf poisscdf poissinv poissrnd poissstat poissfit geopdf geocdf geoinv geornd geostat nbinpdf nbincdf nbininv nbinrnd nbinstat nbinfit nbinlike hygepdf hygecdf hygeinv hygernd hygestat chi2pdf chi2cdf chi2inv chi2rnd chi2stat ncx2pdf ncx2cdf ncx2inv ncx2rnd ncx2stat tpdf tcdf tinv trnd tstat nctpdf nctcdf nctinv nctrnd nctstat fpdf fcdf finv frnd fstat ncfpdf ncfcdf ncfinv ncfrnd ncfstat evpdf evcdf evinv evrnd evstat evfit evlike gevpdf gevcdf gevinv gevrnd gevstat gevfit gevlike gppdf gpcdf gpinv gprnd gpstat gpfit gplike raylpdf raylcdf raylinv raylrnd raylstat raylfit randg'],
    ['Sensitivity analysis and sampling', 'lhsdesign lhsnorm sobolset haltonset net scramble src srrc pcc prcc firstorderindex easi deltamoment mutualinfo pawn discrepancyshares rsa morrisdesign morrisindices soboldesign sobolindices efastdesign efastindices rbdfastdesign rbdfastindices ffdesign ffindices dgsmdesign dgsmindices radialdesign radialindices shapleydesign shapleyindices qrandstream qrand reset'],
    ['Hypothesis tests', 'ttest ttest2 ztest vartest vartest2 vartestn signtest signrank ranksum kstest kstest2 lillietest jbtest adtest chi2gof runstest anova1 anova2 kruskalwallis friedman multcompare crosstab fishertest'],
    ['Regression and curve fitting', 'fitlm fitglm fitnlm predict coefCI coefTest anova plotResiduals regress robustfit ridge glmfit glmval nlinfit nlparci nlpredci partialcorr fit fittype fitoptions confint predint coeffvalues coeffnames numcoeffs differentiate integrate smooth fitlme fixedEffects randomEffects covarianceParameters fitted residuals response sfit cfit excludedata'],
    ['Linear algebra', 'inv det trace rank norm vecnorm cond rcond condest eig eigs svd svds qr lu chol schur hess pinv null orth rref expm logm sqrtm funm cross dot linsolve balance issymmetric ishermitian istril istriu isbanded bandwidth pcg bicg bicgstab cgs gmres minres qmr tfqmr lsqr cholupdate qrupdate qrinsert qrdelete qz ordschur ordeig polyeig givens planerot isdiag normest gsvd ordqz rsf2csf gallery lsqminnorm decomposition isIllConditioned sylvester lscov normest1 subspace condeig cdf2rdf hadamard charpoly minpoly jordan'],
    ['Sparse matrices', 'sparse full issparse nzmax spalloc speye spones sprand sprandn spzeros spdiags spfun spconvert sprandsym spaugment spparms spy amd colamd symamd symrcm dmperm etree sprank ichol ilu symmlq bicgstabl colperm symbfact'],
    ['Special functions', 'gamma gammaln gammainc gammaincinv beta betaln betainc betaincinv erf erfc erfinv erfcinv erfcx expint psi besselj bessely besseli besselk besselh airy ellipke ellipj legendre sinint cosint dawson fresnels fresnelc'],
    ['Polynomials, filters and transforms', 'polyfit polyval polyvalm roots poly conv deconv polyder polyint residue filter filter2 conv2 convn fft ifft fft2 ifft2 fftn ifftn fftshift ifftshift detrend gradient del2 nufft nufftn'],
    ['Interpolation', 'interp1 interp2 interp3 interpn griddata griddedInterpolant scatteredInterpolant spline pchip makima ppval mkpp unmkpp interpft griddatan csaps spaps spapi spmak fnval fnder fnint fnplt fnbrk'],
    ['Optimization', 'fzero fminbnd fminsearch fminunc fmincon fsolve lsqnonlin lsqcurvefit lsqlin lsqnonneg linprog intlinprog quadprog fminimax fgoalattain optimoptions resetoptions optimset optimget optimplotfval optimplotx optimplotfirstorderopt optimplotfunccount optimplotconstrviolation optimplotstepsize optimplotresnorm'],
    ['Apps', 'appdesigner uifigure uibutton uilabel uieditfield uitextarea uidropdown uilistbox uicheckbox uiswitch uislider uispinner uiknob uigauge uilamp uiradiobutton uitogglebutton uiimage uihyperlink uigridlayout uiaxes uialert uiconfirm uiprogressdlg createCallbackFcn registerApp runStartupFcn'],
    ['Classes', 'classdef properties methods ismethod isprop isobject isvalid addlistener listener notify plabSuperCall metaclass meta.class.fromName events copy'],
    ['Mapping', 'deg2km km2deg deg2nm nm2deg deg2sm sm2deg km2nm nm2km km2sm sm2km nm2sm sm2nm km2rad rad2km unitsratio dms2degrees degrees2dms dm2degrees degrees2dm wrapTo180 wrapTo360 wrapToPi wrapTo2Pi referenceEllipsoid wgs84Ellipsoid referenceSphere earthRadius distance azimuth reckon track1 track2 gcwaypts meridianarc antipode areaint areaquad interpm geodetic2ecef ecef2geodetic geodetic2enu enu2geodetic geodetic2ned ned2geodetic geodetic2aer aer2geodetic ecef2enu enu2ecef ecef2ned ned2ecef ecef2aer aer2ecef enu2aer aer2enu ned2aer aer2ned inpolygon polyarea ispolycw poly2cw poly2ccw polysplit polyjoin polyxpoly projcrs geocrs projfwd projinv axesm worldmap setm getm gcm defaultm ismap framem gridm mlabel plabel tightmap showaxes mfwdtran minvtran plotm linem scatterm textm patchm fillm surfm pcolorm contourm geoshow mapshow geoaxes geoplot geoscatter geobubble geolimits geobasemap addCustomBasemap removeCustomBasemap georefcells georefpostings georasterref maprefcells maprefpostings geographicToIntrinsic worldToIntrinsic geointerp shaperead shapeinfo shapewrite readgeoraster geotiffread geotiffinfo'],
    ['Symbolic math', 'sym syms str2sym symfun argnames formula vpa digits subs simplify simplifyFraction expand factor collect combine horner rewrite partfrac numden coeffs poly2sym sym2poly children has lhs rhs isolate finverse compose diff int limit taylor series symsum symprod jacobian hessian gradient divergence curl laplacian solve vpasolve dsolve laplace ilaplace fourier ifourier ztrans iztrans assume assumeAlso assumptions isAlways piecewise heaviside dirac kroneckerDelta sinc lambertw zeta latex pretty char double matlabFunction fplot fpolarplot fimplicit fplot3 fsurf'],
    ['Integration', 'integral integral2 integral3 quadgk quad quadl quad2d dblquad triplequad quadv'],
    ['Differential equations', 'ode45 ode23 ode113 ode78 ode89 ode15s ode23s ode23t ode23tb ode15i decic odeset odeget odeplot deval odextend ode solutionFcn bvp4c bvp5c bvpinit bvpxtend bvpset bvpget dde23 ddesd ddeset ddeget pdepe pdeval'],
    ['Text', 'char string strings cellstr sprintf num2str int2str mat2str str2num str2double strcat strvcat strjoin strsplit split join splitlines strtrim strip deblank blanks pad strjust upper lower reverse strlength strcmp strcmpi strncmp strncmpi contains startsWith endsWith matches strfind strmatch count strtok strrep replace erase extractBefore extractAfter extractBetween replaceBetween eraseBetween insertAfter insertBefore regexp regexpi regexprep regexptranslate isspace isletter isstrprop istext dec2bin bin2dec dec2hex hex2dec dec2base base2dec num2hex hex2num compose newline sscanf validatestring convertCharsToStrings convertStringsToChars pattern digitsPattern lettersPattern alphanumericsPattern whitespacePattern wildcardPattern characterListPattern optionalPattern asManyOfPattern asFewOfPattern letterBoundary digitBoundary alphanumericBoundary whitespaceBoundary lineBoundary textBoundary lookAheadBoundary lookBehindBoundary regexpPattern caseInsensitivePattern caseSensitivePattern namedPattern extract isStringScalar matlab.net.base64encode matlab.net.base64decode unicode2native native2unicode textwrap'],
    ['Cells, structs and maps', 'cell cellfun num2cell cell2mat mat2cell celldisp cell2struct struct2cell struct fieldnames isfield rmfield setfield getfield orderfields arrayfun structfun dictionary insert lookup numEntries isConfigured types entries containers.Map keys values isKey remove deal iscell iscellstr isstruct'],
    ['Types', 'class isa isnumeric isfloat isinteger islogical ischar isstring isobject double single int8 uint8 int16 uint16 int32 uint32 int64 uint64 logical cast typecast swapbytes func2str str2func symvar feval functions enumeration import'],
    ['Parallel loops', 'parfor parpool gcp getCurrentTask spmd labindex spmdIndex numlabs spmdSize backgroundPool parfeval parfevalOnAll fetchOutputs fetchNext afterEach afterAll cancel'],
    ['Programs and the workspace', 'disp display fprintf input keyboard error warning lasterr lastwarn MException throw rethrow throwAsCaller addCause getReport assert onCleanup exist clear clearvars who whos eval evalin evalc assignin inputname mfilename nargin nargout narginchk nargoutchk validateattributes isvarname iskeyword genvarname matlab.lang.makeValidName matlab.lang.makeUniqueStrings namelengthmax builtin format clc more echo diary beep sound soundsc profile help version ver computer ispc ismac isunix isdeployed usejava matlabroot userpath getenv setenv web exit quit dbstop dbclear dbstatus dbstack checkcode mlint clipboard lookfor memoize clearCache clearAllMemoizedCaches stats timeit setpref addpref getpref ispref rmpref subsref subsasgn substruct namedargs2cell isMATLABReleaseOlderThan verLessThan'],
    ['The desktop and the engine', 'commandwindow commandhistory workspace filebrowser openvar matlabRelease maxNumCompThreads memory license'],
    ['Missing data and outliers', 'missing ismissing fillmissing rmmissing standardizeMissing isoutlier filloutliers smoothdata findgroups splitapply rmoutliers'],
    ['Checking arguments', 'validateattributes validatestring inputParser addRequired addOptional addParameter addParamValue parse narginchk nargoutchk nargchk mustBePositive mustBeNonnegative mustBeNegative mustBeNonpositive mustBeNonzero mustBeInteger mustBeNumeric mustBeNumericOrLogical mustBeFloat mustBeReal mustBeFinite mustBeNonNan mustBeNonempty mustBeNonsparse mustBeGreaterThan mustBeGreaterThanOrEqual mustBeLessThan mustBeLessThanOrEqual mustBeInRange mustBeMember mustBeText mustBeTextScalar mustBeNonzeroLengthText mustBeVector mustBeScalarOrEmpty mustBeA mustBeUnderlyingType mustBeNonmissing mustBeValidVariableName mustBeFile mustBeFolder'],
    ['Geometry', 'delaunay convhull voronoi voronoin tsearchn dsearchn inpolygon polyarea rectint triplot trisurf trimesh delaunayn convhulln'],
    ['Triangulations and polygons', 'triangulation delaunayTriangulation pointLocation nearestNeighbor edges vertexAttachments edgeAttachments isConnected freeBoundary circumcenter incenter barycentricToCartesian cartesianToBarycentric faceNormal vertexNormal featureEdges convexHull voronoiDiagram isInterior polyshape nsidedpoly centroid perimeter boundingbox boundary numboundaries numsides ishole issimplified isinterior nearestvertex overlaps regions holes addboundary rmboundary rmholes rmslivers scale translate sortboundaries sortregions subtract polybuffer alphaShape alphaSpectrum criticalAlpha alphaTriangulation boundaryFacets inShape numRegions surfaceArea volume'],
    ['NetCDF files', 'nccreate ncwrite ncread ncinfo ncdisp ncreadatt ncwriteatt'],
    ['Parquet and FITS files', 'parquetread parquetwrite parquetinfo fitsread fitsinfo fitsdisp fitswrite'],
    ['Images, sound and the web', 'imread imwrite imfinfo image imagesc audioread audiowrite audioinfo sound soundsc webread webwrite websave weboptions web VideoWriter writeVideo VideoReader hasFrame readFrame read audioplayer play playblocking isplaying resume audiorecorder record recordblocking getaudiodata isrecording'],
    ['Dates and time', 'tic toc pause cputime clock now date datenum datestr datevec etime weekday eomday addtodate leapyear calendar'],
    ['Dates and durations', 'datetime NaT isdatetime isnat year quarter month week day hour minute second ymd hms timeofday isweekend isbetween posixtime juliandate exceltime convertTo tzoffset dateshift between caldiff duration isduration years days hours minutes seconds milliseconds calendarDuration iscalendarduration calyears calquarters calmonths calweeks caldays'],
    ['Categorical arrays', 'categorical categories iscategorical isordinal isprotected isundefined iscategory countcats addcats removecats mergecats renamecats reordercats setcats summary'],
    ['Tables and timetables', 'table timetable istable istimetable istabular height width head tail vartype timerange table2array table2cell table2struct struct2table cell2table array2table table2timetable timetable2table addvars removevars movevars renamevars splitvars mergevars rows2vars convertvars varfun rowfun groupsummary innerjoin outerjoin join sortrows retime synchronize isregular readtable writetable summary stack unstack groupcounts grouptransform groupfilter pivot topkrows lag array2timetable writetimetable'],
    ['Fuzzy logic', 'mamfis sugfis newfis addInput addOutput addvar addMF addmf removeMF removeInput removeOutput addRule addrule evalfis evalfisOptions evalmf fismf defuzz showrule plotmf gensurf readfis writefis trimf trapmf gaussmf gauss2mf gbellmf sigmf dsigmf psigmf pimf smf zmf linsmf linzmf'],
    ['System identification', 'iddata idinput arx ar armax oe bj n4sid ssest tfest compare sim pe resid polydata present aic fpe'],
    ['Communications', 'awgn qammod qamdemod pskmod pskdemod pammod pamdemod int2bit bit2int de2bi bi2de bin2gray gray2bin biterr symerr berawgn rcosdesign eyediagram scatterplot'],
    ['Audio features', 'hz2mel mel2hz melSpectrogram mfcc pitch spectralCentroid spectralSpread spectralRolloffPoint spectralFlatness spectralEntropy zerocrossrate'],
    ['Finance', 'blsprice blsdelta blsgamma blsvega blstheta blsrho blslambda blsimpv blkprice binprice irr mirr xirr pvvar fvvar pvfix fvfix payper amortize annurate annuterm effrr nomrr price2ret ret2price tick2ret ret2tick ewstats movavg bollinger rsindex macd daysact days360 yearfrac holidays isbusday busdate fbusdate lbusdate Portfolio setAssetMoments estimateAssetMoments setDefaultConstraints setBounds setBudget setInequality setEquality estimateFrontier estimateFrontierLimits estimateFrontierByReturn estimateFrontierByRisk estimateMaxSharpeRatio estimatePortReturn estimatePortRisk estimatePortMoments plotFrontier portopt portstats portvrisk corr2cov cov2corr'],
    ['Econometrics', 'arima garch egarch gjr varm estimate forecast simulate infer summarize impulse irf fevd autocorr parcorr crosscorr adftest pptest kpsstest lbqtest archtest vratiotest egcitest aicbic lratiotest waldtest lmtest hpfilter lagmatrix'],
    ['Datastores and tall arrays', 'datastore tabularTextDatastore spreadsheetDatastore imageDatastore fileDatastore parquetDatastore arrayDatastore readall hasdata preview progress numpartitions partition shuffle subset transform isPartitionable isShuffleable countEachLabel splitEachLabel writeall mapreduce add addmulti hasnext getnext tall gather istall classUnderlying isaUnderlying'],
    ['Signal processing', 'butter cheby1 cheby2 ellip buttord cheb1ord cheb2ord ellipord fir1 fir2 firls firpm remez kaiserord designfilt filtfilt sosfilt fftfilt filtic upfirdn medfilt1 sgolay sgolayfilt hilbert envelope lowpass highpass bandpass bandstop freqz freqs impz stepz grpdelay zplane filtord tf2zp zp2tf tf2sos zp2sos sos2tf sos2zp xcorr xcov resample decimate interp downsample upsample buffer findpeaks hamming hann hanning blackman flattopwin blackmanharris nuttallwin kaiser bartlett triang rectwin gausswin tukeywin chebwin barthannwin bohmanwin parzenwin window periodogram pwelch cpsd mscohere tfestimate spectrogram bandpower chirp sawtooth square rectpuls tripuls gauspuls diric db2mag mag2db pow2db db2pow peak2peak peak2rms rceps dct idct besself residuez stft istft pulstran cceps icceps pspectrum instfreq finddelay alignsignals dtw edr emd vmd wvd'],
    ['Pulse and tone measurements', 'snr thd sinad sfdr statelevels midcross risetime falltime slewrate pulsewidth pulsesep pulseperiod dutycycle overshoot undershoot settlingtime'],
    ['Image processing', 'imresize imrotate imcrop imtranslate imfilter fspecial imgaussfilt medfilt2 edge stretchlim imadjust imhist histeq graythresh imbinarize imcomplement strel imdilate imerode imopen imclose imfill bwlabel bwconncomp regionprops imtile montage bwmorph bwboundaries adapthisteq imhistmatch otsuthresh multithresh imquantize im2bw imgradientxy imgradient bwlabeln bwareaopen bwareafilt bwpropfilt bwperim bwdist bwskel bwconvhull bweuler bwarea bwselect bwtraceboundary imreconstruct imregionalmax imregionalmin imhmax imhmin imextendedmax imextendedmin imimposemin watershed imclearborder imtophat imbothat label2rgb labeloverlay imoverlay imadd imsubtract immultiply imdivide imabsdiff imlincomb imnoise imsharpen imfuse imshowpair corr2 immse psnr ssim entropy entropyfilt stdfilt rangefilt imboxfilt integralImage imguidedfilter imbilatfilt imdiffusefilt imgaussfilt3 ordfilt2 wiener2 psf2otf otf2psf deconvwnr deconvlucy padarray im2col col2im blockproc nlfilter colfilt impyramid improfile imcontour hough houghpeaks houghlines imfindcircles radon iradon phantom dct2 idct2 dctmtx'],
    ['Image geometry and registration', 'affine2d projective2d affinetform2d projtform2d rigidtform2d simtform2d transltform2d transformPointsForward transformPointsInverse invert outputLimits isTranslation isRigid isSimilarity imref2d worldToIntrinsic intrinsicToWorld worldToSubscript sizesMatch imwarp fitgeotrans fitgeotform2d imregcorr'],
    ['Images and colours', 'imread imwrite imfinfo image imagesc imshow im2double im2single im2uint8 im2uint16 rgb2gray im2gray cmap2gray mat2gray rgb2hsv hsv2rgb rgb2lightness ind2rgb ind2gray gray2ind rgb2ind imsplit rgb2lab lab2rgb rgb2xyz xyz2rgb rgb2ycbcr ycbcr2rgb im2int16'],
    ['Files and folders', 'pwd cd dir ls what which type edit open run mkdir rmdir delete copyfile movefile zip unzip gzip gunzip tar untar fullfile fileparts filesep pathsep tempdir tempname isfile isfolder isdir addpath rmpath path genpath rehash fopen fclose fgetl fgets fread fwrite fprintf fscanf feof ferror frewind ftell fseek fileread readlines writelines textscan textread readmatrix jsondecode jsonencode writematrix csvread csvwrite dlmread dlmwrite readcell writecell load save matfile importdata h5create h5write h5read h5readatt h5writeatt h5info h5disp readstruct writestruct xlsread xlswrite xlsfinfo readtimetable detectImportOptions setvartype setvaropts getvaropts readvars xmlread xmlwrite com.mathworks.xml.XMLUtils.createDocument fileattrib recycle'],
    ['Line and area plots', 'plot plot3 line semilogx semilogy loglog fplot ezplot scatter scatter3 bubblechart bubblechart3 bubblesize bubblelim bar barh histogram hist area fill fill3 patch stairs stem errorbar pie polarplot fpolarplot polarscatter polarbubblechart polaraxes polar quiver quiver3 compass feather rose pareto stem3 comet comet3 bar3 bar3h histogram2 pie3 ribbon animatedline addpoints clearpoints getpoints xline yline xregion yregion swarmchart swarmchart3 plotyy gplot treelayout treeplot etreeplot ezplot3 ezpolar'],
    ['Charts', 'heatmap piechart donutchart stackedplot polarhistogram wordcloud'],
    ['Clustering and dimensions', 'pdist pdist2 squareform knnsearch rangesearch mahal kmeans kmedoids linkage cluster clusterdata cophenet inconsistent optimalleaforder dendrogram dbscan spectralcluster gmdistribution fitgmdist posterior silhouette evalclusters pca pcacov ppca factoran rotatefactors cmdscale mdscale tsne procrustes canoncorr barttest nnmf corrcov createns KDTreeSearcher ExhaustiveSearcher'],
    ['Classification and regression', 'fitctree fitrtree fitcknn fitcdiscr fitcnb fitcsvm fitrsvm fitcecoc fitcensemble fitrensemble TreeBagger fitclinear fitrlinear fitcnet fitrnet fitrgp fitckernel fitrkernel templateTree templateSVM templateKNN templateDiscriminant templateNaiveBayes templateLinear templateKernel templateGP predict loss resubLoss resubPredict crossval kfoldLoss kfoldPredict oobLoss oobPredict compact view cvpartition training test repartition confusionmat confusionchart perfcurve'],
    ['More statistics', 'lasso stepwiselm anovan manova1 bootci ansaribradley copularnd copulapdf copulacdf copulastat copulaparam copulafit coxphfit hmmgenerate hmmviterbi hmmdecode hmmestimate hmmtrain relieff fscchi2 fscmrmr sequentialfs andrewsplot parallelcoords probplot tiedrank ecdfhist mnrfit mnrval rocmetrics'],
    ['Design of experiments', 'fullfact ff2n fracfact bbdesign ccdesign candgen candexch rowexch cordexch daugment dcovary'],
    ['Control systems', 'tf zpk ss pid feedback series parallel tfdata zpkdata ssdata ss2tf tf2ss pole zero tzero dcgain evalfr freqresp damp isstable ctrb obsv gram covar lyap dlyap care dare lqr dlqr lqry lqe kalman estim reg place acker getPeakGain hinfnorm norm bandwidth c2d d2c pade minreal ss2ss xperm canon hsvd balreal balred modred step impulse initial stepplot impulseplot lsim stepinfo bode bodeplot nyquist nichols sigma margin allmargin rlocus pzmap frd frdata bodemag lsiminfo append sumblk connect d2d ctrbf obsvf lqi pidtune pidtuneOptions'],
    ['Wavelets', 'wfilters dbwavf symwavf coifwavf qmf orthfilt biorfilt dwtmode wmaxlev dwt idwt wavedec waverec appcoef detcoef wrcoef upcoef wenergy dwt2 idwt2 wavedec2 waverec2 appcoef2 detcoef2 wrcoef2 swt iswt swt2 iswt2 modwt imodwt modwtmra wavefun centfrq scal2frq cwt icwt cwtfreqbounds wthresh wnoisest thselect wden ddencmp wdenoise wcodemat cwtfilterbank wt scales centerFrequencies centerPeriods timeSpreads dwtfilterbank scalingfunctions wavelets framebounds dwtpassbands wsst iwsst wcoherence ewt'],
    ['Global optimization', 'ga particleswarm simulannealbnd patternsearch surrogateopt gamultiobj paretosearch createOptimProblem MultiStart GlobalSearch run optimoptions'],
    ['Problem-based optimization', 'optimvar optimexpr optimconstr optimineq optimeq optimproblem eqnproblem solve evaluate infeasibility fcn2optimexpr prob2struct varindex show showbounds'],
    ['Partial differential equations', 'createpde decsg geometryFromEdges generateMesh specifyCoefficients applyBoundaryCondition setInitialConditions solvepde solvepdeeig assembleFEMatrices interpolateSolution evaluateGradient pdeplot pdegplot pdemesh findNodes findElements meshToPet'],
    ['Unit tests', 'runtests testsuite matlab.unittest.TestSuite.fromFile matlab.unittest.TestSuite.fromFolder matlab.unittest.TestSuite.fromName matlab.unittest.TestSuite.fromClass functiontests localfunctions matlab.unittest.TestCase.forInteractiveUse matlab.unittest.TestRunner.withTextOutput matlab.unittest.TestRunner.withNoPlugins assertSuccess addTeardown verifyEqual verifyNotEqual verifyTrue verifyFalse verifyError verifyWarning verifyWarningFree verifyEmpty verifyNotEmpty verifySize verifyLength verifyNumElements verifyClass verifyInstanceOf verifyGreaterThan verifyGreaterThanOrEqual verifyLessThan verifyLessThanOrEqual verifyReturnsTrue verifySubstring verifyMatches verifyFail verifySameHandle verifyNotSameHandle assertEqual assertNotEqual assertTrue assertFalse assertError assertWarning assertWarningFree assertEmpty assertNotEmpty assertSize assertLength assertNumElements assertClass assertInstanceOf assertGreaterThan assertGreaterThanOrEqual assertLessThan assertLessThanOrEqual assertReturnsTrue assertSubstring assertMatches assertFail assertSameHandle assertNotSameHandle fatalAssertEqual fatalAssertNotEqual fatalAssertTrue fatalAssertFalse fatalAssertError fatalAssertWarning fatalAssertWarningFree fatalAssertEmpty fatalAssertNotEmpty fatalAssertSize fatalAssertLength fatalAssertNumElements fatalAssertClass fatalAssertInstanceOf fatalAssertGreaterThan fatalAssertGreaterThanOrEqual fatalAssertLessThan fatalAssertLessThanOrEqual fatalAssertReturnsTrue fatalAssertSubstring fatalAssertMatches fatalAssertFail fatalAssertSameHandle fatalAssertNotSameHandle assumeEqual assumeNotEqual assumeTrue assumeFalse assumeError assumeWarning assumeWarningFree assumeEmpty assumeNotEmpty assumeSize assumeLength assumeNumElements assumeClass assumeInstanceOf assumeGreaterThan assumeGreaterThanOrEqual assumeLessThan assumeLessThanOrEqual assumeReturnsTrue assumeSubstring assumeMatches assumeFail assumeSameHandle assumeNotSameHandle'],
    ['Calling Python', 'pyrun pyrunfile pyenv pyargs'],
    ['Graphs and networks', 'graph digraph numnodes numedges findnode findedge degree indegree outdegree neighbors successors predecessors outedges inedges edgecount adjacency incidence laplacian ismultigraph addedge rmedge addnode rmnode subgraph reordernodes flipedge simplify shortestpath distances nearest shortestpathtree bfsearch dfsearch allpaths conncomp biconncomp condensation toposort isdag hascycles transclosure transreduction minspantree maxflow centrality isisomorphic highlight labelnode labeledge layout'],
    ['Statistical plots', 'boxplot gscatter gplotmatrix plotmatrix scatterhist histfit normplot qqplot cdfplot lsline refline refcurve boxchart binscatter parallelplot scatterhistogram'],
    ['Surfaces, contours and images', 'contour contourf contour3 contourc clabel fcontour ezcontour surf surfc surfl mesh meshc meshz waterfall pcolor surface fsurf fmesh ezsurf ezmesh image imagesc imshow peaks sphere cylinder ellipsoid shading view camzoom camva light camlight lighting material colorbar colormap clim caxis alpha hidden isosurface slice stream2 stream3 streamline coneplot streamtube contourslice fimplicit3 tetramesh isocaps isonormals smooth3 reducepatch reducevolume subvolume volumebounds streamslice streamparticles surfnorm shrinkfaces isocolors ezsurfc ezmeshc ezcontourf streamribbon camlookat specular diffuse'],
    ['Figures and axes', 'figure clf close gcf gca gco groot axes polaraxes cla subplot tiledlayout nexttile hold ishold newplot axis xlim ylim zlim xticks yticks zticks xticklabels yticklabels zticklabels xtickangle ytickangle grid box daspect pbaspect yyaxis colororder title subtitle sgtitle suptitle xlabel ylabel zlabel legend text annotation set get findobj findall allchild ancestor copyobj gobjects ishandle ishghandle isgraphics isvalid isprop drawnow refresh shg getframe frame2im im2frame movie saveas exportgraphics print savefig openfig hgsave hgload ginput waitforbuttonpress zoom pan rotate3d datacursormode plotedit inspect brush linkaxes linkprop whitebg camorbit campos camtarget camup camroll datetick rectangle hggroup hgtransform makehgtform rotate refreshdata xtickformat ytickformat ztickformat ztickangle rticks thetaticks rticklabels thetaticklabels rlim gtext lightangle orient copygraphics'],
    ['User interfaces', 'uicontrol uipanel uibuttongroup uitable uitabgroup uitab uimenu uicontextmenu uitoolbar uipushtool uitoggletool gcbo gcbf closereq uiwait uiresume waitfor guidata setappdata getappdata isappdata rmappdata msgbox errordlg warndlg helpdlg questdlg inputdlg listdlg menu uigetfile uiputfile uigetdir uisetcolor waitbar dialog printdlg printpreview helpwin doc timer start stop wait timerfind timerfindall movegui uistack'],
    ['Colormaps', 'parula viridis turbo jet gray hot cool spring summer autumn winter bone copper pink hsv lines prism flag white colorcube brighten rgbplot spinmap validatecolor rgb2hex hex2rgb'],
  ];

  /* ---- function pages -------------------------------------------------------------
     Written in resources/data/pylab-docs/src and built by
     resources/tests/pylab/pylab_docs.py, which ran each example in PyLAB:
     its output and its figures (as figure windows get them) are stored with
     it, and the figures are drawn here by the figure windows' renderer. */
  const DOCS = 'resources/data/pylab-docs/';
  let docIndex = null;
  const docFiles = new Map();

  function docJson(path) {
    const v = document.documentElement.dataset.build || '';
    return fetch(`${DOCS}${path}?v=${encodeURIComponent(v)}`).then((r) => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return r.json();
    });
  }

  // arrays most figures share (the default colormap) are kept once in index.json;
  // arrays kept in single precision are widened to the doubles the renderer reads
  function single(o) {
    const bin = atob(o.$);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return { data: Float64Array.from(new Float32Array(u8.buffer)), shape: o.shape };
  }

  function withShared(o, shared) {
    if (Array.isArray(o)) return o.map((v) => withShared(v, shared));
    if (o && typeof o === 'object') {
      if (typeof o.$ref === 'string') return shared[o.$ref] || null;
      if (typeof o.$ === 'string' && o.dt === 'f4') return single(o);
      const out = {};
      for (const k of Object.keys(o)) out[k] = withShared(o[k], shared);
      return out;
    }
    return o;
  }

  function docNames() {
    if (!docIndex) docIndex = docJson('index.json').catch(() => ({ names: {}, shared: {} }));
    return docIndex;
  }

  async function docPage(name) {
    const idx = await docNames();
    const slug = idx.names[name];
    if (!slug) return null;
    if (!docFiles.has(slug)) docFiles.set(slug, docJson(`${slug}.json`).then((d) => withShared(d, idx.shared)));
    const d = await docFiles.get(slug).catch(() => null);
    return d ? d.pages.find((p) => p.names.includes(name)) || null : null;
  }

  // text with `code` in it: a function's name in backticks links to its help
  function inline(text, known) {
    const out = [];
    text.split(/(`[^`]*`)/).forEach((part) => {
      if (part.length > 1 && part[0] === '`' && part.endsWith('`')) {
        const s = part.slice(1, -1);
        const code = el('code', null, s);
        out.push(/^[A-Za-z]\w*$/.test(s) && known.has(s) ? el('a', { href: '#', class: 'pl-helplink', 'data-help': s }, code) : code);
      } else if (part) out.push(part);
    });
    return out;
  }

  function codeBlock(code, cls) {
    const pre = el('pre', { class: cls });
    pre.innerHTML = PL.lang.highlight(code);
    return pre;
  }

  /* A stored figure on a canvas the width of its place (at most its own),
     drawn again when that changes. */
  function figureCanvas(fig) {
    const canvas = el('canvas', { class: 'pl-doc-fig', role: 'img', 'aria-label': fig.name || `Figure ${fig.number}` });
    const box = el('div', { class: 'pl-doc-figbox', style: { maxWidth: `${Math.round(fig.width) || 560}px` } }, canvas);
    // an app's components are HTML over the canvas, as in a figure window (pylab-ui.js); here only to be looked at
    let layer = null;
    if ((fig.controls || []).length && PL.FigureUI) {
      const ui = new PL.FigureUI({ canvas, el: box, mgr: { ui() {} }, redrawSoon() {} });
      layer = ui.layer;
      layer.classList.add('pl-doc-uilayer');
      layer.setAttribute('inert', '');
      layer.style.width = `${fig.width}px`;
      layer.style.height = `${fig.height}px`;
      box.append(layer);
      ui.update(fig);
    }
    let lastW = 0;
    const draw = () => {
      const avail = box.clientWidth;
      if (!avail || !fig.width) return;
      const w = Math.min(fig.width, avail);
      if (Math.abs(w - lastW) < 1) return;
      lastW = w;
      const h = Math.round(w * fig.height / fig.width);
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const before = PL.figureCtx;
      PL.figureCtx = ctx;
      try { new PL.FigureRenderer().draw(ctx, fig, w, h); } finally { PL.figureCtx = before; }
      if (layer) layer.style.transform = `scale(${w / fig.width})`;
    };
    if (typeof ResizeObserver === 'function') new ResizeObserver(draw).observe(box);
    requestAnimationFrame(draw);
    return box;
  }

  class HelpView {
    constructor(app) {
      this.app = app;
      this.el = el('div', { class: 'pl-help' });
      // a function named in a help text, or in its See also line: its help here
      this.el.addEventListener('click', (ev) => {
        const a = ev.target.closest('[data-help]');
        if (a) { ev.preventDefault(); this.show(a.dataset.help); }
      });
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
          el('li', null, 'Every window is a tab: drag a tab by its title onto another strip of tabs to stack it there, or onto the edge of a window to split that side off. The bars between the windows resize them. Layout (HOME tab) shows and hides the windows and brings back the default layout.'),
          el('li', null, 'The Current Folder lists your files; right-click a file to download it.'),
          el('li', null, 'Double-click a variable in the Workspace to see it as a table. Select variables and pick a chart in the PLOTS tab.'),
          el('li', null, 'Figures open in windows of their own; the dock button in a figure\u2019s title bar puts it in the desktop as a tab (and back), and Layout can dock every new figure. In a figure, drag to pan (or to turn a 3-D view), scroll to zoom, double-click to go back; the toolbar has zoom by box and data tips, and the button beside the title saves the figure as a picture (PNG, JPEG) or as a drawing whose lines and text stay sharp at any size (SVG, PDF, EPS).'),
          el('li', null, 'To change a figure without commands, press the arrow at the left of its toolbar: the property editor opens beside it. Click a part of the figure (a line, the axes, the title, a label, the legend, the colorbar, an annotation, a control), or pick it in the editor\u2019s list of the figure\u2019s objects, and change its properties in the fields: colours, line styles, markers, limits, scales, grids, fonts, text and the rest. A change applies when you press Enter or leave the field. Properties a program can set but the page does not draw are listed last, under Kept, not drawn. inspect(h) and plotedit do the same from a program.'),
          el('li', null, 'Programs can make windows of their own, with controls, menus, toolbars, context menus and dialogs (uicontrol, uimenu, msgbox and the rest under User interfaces); their callbacks run when someone uses them. ',
            el('code', null, 'examples/wavelab.m'), ' is one.'),
          el('li', null, 'View Python in the EDITOR tab shows the Python a file compiles to.')),
        el('h3', null, 'Keys'),
        keysTable(k),
        el('h3', null, 'The language here'),
        el('ul', null,
          el('li', null, 'Scripts, functions with local and nested functions, anonymous functions and handles, cell arrays, structs and struct arrays, string arrays, integer and single types, logical indexing, ', el('code', null, 'end'), ' in indices, implicit expansion, comma-separated lists, varargin and varargout, global and persistent variables, try/catch with error identifiers, arguments blocks (sizes, classes, validators and name-value arguments), classes of your own (classdef files: handle and value classes, events, enumerations), packages (+folders) and import, ', el('code', null, 'containers.Map'), ' and ', el('code', null, 'dictionary'), '.'),
          el('li', null, 'Not here: Simulink, live scripts (.mlx), Java, MEX files, and the toolboxes beyond the functions listed below.'),
          el('li', null, 'Numbers are IEEE doubles, as NumPy and SciPy compute them; random numbers come from a Mersenne Twister, and rand with the default seed gives the usual first numbers.'),
          el('li', null, 'Signal processing: filter design (Butterworth, Chebyshev, elliptic, window and least-squares FIR, designfilt), zero-phase and other filtering, frequency responses, windows, correlation, resampling, peaks and envelopes, and spectra (periodogram, Welch, spectrogram, coherence), computed with SciPy.'),
          el('li', null, 'Regression and curve fitting: linear, robust, generalized linear and nonlinear models (fitlm, fitglm, fitnlm and regress, glmfit, nlinfit), curve fits of library models, expressions, interpolants and smoothing splines (fit), and smoothing, local extrema, abrupt changes and trends of data, computed with NumPy and SciPy.'),
          el('li', null, 'Images: resizing, rotating and filtering, edges, contrast and thresholds, morphology and connected components. Files: HDF5 (h5read and the rest, through h5py), structs in XML and JSON, spreadsheets, and AVI videos written and read (VideoWriter, VideoReader).'),
          el('li', null, 'The profiler (profile on, profile viewer), the diary, breakpoints from commands (dbstop, also if error), dbstack and the code checker (checkcode).'),
          el('li', null, 'Statistics: probability distributions (their functions, fits and distribution objects), descriptive statistics, hypothesis tests and statistical plots, computed with SciPy. The lists below have them all.'),
          el('li', null, 'MAT-files of versions 4 to 7 load and save; version 7.3 files load.')),
        el('h3', null, 'Functions'),
        el('p', { class: 'pl-doc-legend' }, 'Names in bold have a page of their own, with examples and what they give; the others show their summary, forms and how PyLAB computes them.'),
        ...lists.flat(),
        el('p', { class: 'pl-notice' }, 'MATLAB is a registered trademark of The MathWorks, Inc. PyLAB is not made by The MathWorks and is not affiliated with or endorsed by it; it runs programs written in the same language.'),
      );
      this.el.scrollTop = 0;
      docNames().then((idx) => {
        for (const a of this.el.querySelectorAll('.pl-fnlist a[data-fn]')) if (idx.names[a.dataset.fn]) a.classList.add('has-doc');
      });
    }

    async show(name) {
      let h;
      const [got, page] = await Promise.all([
        PL.engine.call('help_text', name).catch((e) => ({ text: `${name}: ${e.message}` })),
        docPage(name).catch(() => null),
      ]);
      h = got;
      const back = el('button', { class: 'pl-btn', type: 'button' }, '← All functions');
      back.addEventListener('click', () => this.home());
      let parts;
      if (page) parts = [back, ...await this.docParts(name, page)];
      else {
        const pre = el('pre');
        PL.appendLinked(pre, h.base_linked || h.linked || h.base || h.text);
        parts = [back, el('h2', null, name), pre];
      }
      // how PyLAB computes it, as paragraphs (the Command Window has them wrapped into its text)
      const how = h.how_linked || h.how;
      if (how && how.length) {
        const sec = el('section', { class: 'pl-how' }, el('h3', null, 'How it works'));
        for (const b of how) {
          if (b.pre !== undefined) { sec.append(el('pre', null, b.pre)); continue; }
          const p = el('p');
          PL.appendLinked(p, b.p);
          sec.append(p);
        }
        parts.push(sec);
      }
      // related functions, each a link (a page's own list first)
      if (page && page.see.length) h.see = page.see;
      if (h.see && h.see.length) {
        const see = el('p', { class: 'pl-see' }, el('strong', null, 'See also: '));
        h.see.forEach((n, i) => {
          if (i) see.append(', ');
          see.append(el('a', { href: '#', class: 'pl-helplink', 'data-help': n }, n));
        });
        parts.push(see);
      }
      if (h.kind === 'file') {
        const open = el('button', { class: 'pl-btn', type: 'button' }, 'Open in the Editor');
        open.addEventListener('click', () => this.app.openFile(h.path));
        parts.push(open);
      }
      this.el.replaceChildren(...parts);
      this.el.scrollTop = 0;
    }

    /* A function's page: what it does, its forms, inputs and outputs, and
       examples with what they print and draw (Run, Open in Editor, Copy). */
    async docParts(name, page) {
      const known = new Set([...Object.keys((await docNames()).names), ...CATEGORIES.flatMap(([, n]) => n.split(' '))]);
      const parts = [el('h2', null, page.names.join(', ')), el('p', { class: 'pl-doc-summary' }, ...inline(page.summary, known))];
      for (const b of page.body) parts.push(el('p', { class: 'pl-doc-p' }, ...inline(b, known)));
      if (page.syntax.length) {
        const box = el('div', { class: 'pl-doc-syntax' });
        for (const [code, text] of page.syntax) box.append(el('div', { class: 'pl-doc-form' }, codeBlock(code, 'pl-doc-sig'), text ? el('p', null, ...inline(text, known)) : ''));
        parts.push(el('h3', null, 'Syntax'), box);
      }
      for (const [title, items] of [['Inputs', page.inputs], ['Outputs', page.outputs]]) {
        if (!items.length) continue;
        const dl = el('dl', { class: 'pl-doc-args' });
        // (an argument's name is no function's, even when it is spelt as one: format)
        for (const [head, text] of items) dl.append(el('dt', null, ...inline(head.replace(/^([^—]+?)(\s+—)/, '`$1`$2'), new Set())), el('dd', null, ...inline(text, known)));
        parts.push(el('h3', null, title), dl);
      }
      if (page.examples.length) {
        parts.push(el('h3', null, 'Examples'));
        for (const ex of page.examples) parts.push(this.example(ex, known));
      }
      if (page.notes.length) {
        parts.push(el('h3', null, 'Notes'));
        for (const n of page.notes) parts.push(el('p', { class: 'pl-doc-p' }, ...inline(n, known)));
      }
      return parts;
    }

    example(ex, known) {
      // over the code's upper right corner: Run, Open in Editor, Copy
      const btn = (name, title, fn, cls) => {
        const b = el('button', { class: 'pl-iconbtn', type: 'button', title, 'aria-label': title }, PL.icon(name, cls));
        b.addEventListener('click', fn);
        return b;
      };
      const tools = el('div', { class: 'pl-doc-tools', role: 'toolbar', 'aria-label': `Example: ${ex.title}` },
        btn('run', 'Run the example in the Command Window', () => { this.app.activePanel?.(this.app.pCmd); this.app.runCommand(ex.code); }, 'pl-ic-run'),
        btn('newscript', 'Open the example in the Editor, as a new script', () => this.app.newScript(`${ex.code}\n`)),
        btn('copy', 'Copy the code', () => { navigator.clipboard?.writeText(ex.code); U().toast('Copied.'); }));
      const sec = el('section', { class: 'pl-doc-ex' }, el('h4', null, ex.title));
      if (ex.intro) sec.append(el('p', { class: 'pl-doc-p' }, ...inline(ex.intro, known)));
      sec.append(el('div', { class: 'pl-doc-codebox' }, codeBlock(ex.code, 'pl-doc-code'), tools));
      if (ex.output) sec.append(el('pre', { class: 'pl-doc-out', 'aria-label': 'What it prints' }, ex.output));
      if (ex.figures && ex.figures.length) sec.append(el('div', { class: 'pl-doc-figs' }, ...ex.figures.map(figureCanvas)));
      if (ex.after) sec.append(el('p', { class: 'pl-doc-p' }, ...inline(ex.after, known)));
      return sec;
    }
  }

  const U = () => PL.util;

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
  PL.helpDocs = { names: docNames, page: docPage };
  PL.helpCategories = CATEGORIES;
})(window);
