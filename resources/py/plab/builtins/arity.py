"""The fewest inputs each built-in takes: called with fewer, it gives the
language's error (MATLAB:minrhs, "Not enough input arguments.") before it
runs, as a function with declared inputs does. The functions that check
their inputs themselves (nargchk), and those that take any number, are not
listed. The counts are the shortest call forms each function has."""
from ._util import err

MIN_INPUTS = {}
for _n in """
allchild and area argnames array2table assume assumeAlso balance bar barh bin2dec blanks builtin categorical
categories ceil cell2table children coeffs collect combine compan compose cond condest contour contour3 contourc
contourf countcats createCallbackFcn csvread csvwrite ctranspose cummax cummin curl datevec deg2km deg2nm deg2sm
degrees2dm degrees2dms detrend dirac divergence dlmread dlmwrite dm2degrees dms2degrees eigs ellipke etime expand
expm ezcontour ezmesh ezplot ezsurf factor fcontour feof fft2 fftn fftshift fgetl fgets fileparts fileread fimplicit
finverse fix floor fmesh formula fourier fplot fread frewind fscanf fseek fsurf ftell functions fwrite genpath
genvarname geographicToIntrinsic geoshow geotiffinfo geotiffread getenv getfield getm getReport hankel head height
hess hessian hex2dec hex2num hilb hist horner ifft2 ifftn ifftshift ifourier ilaplace importdata imshow int int2str
invhilb iqr isAlways iscategorical isdir isfile isfolder isgraphics ishandle ishghandle isletter isobject isordinal
isprotected isregular isspace istable istabular istimetable isundefined isvalid isvarname iztrans jacobian join keys
km2deg km2nm km2rad km2sm kroneckerDelta lambertw laplace laplacian latex leapyear lhs limit logm mapshow matfile
matlab.lang.makeValidName mesh meshc meshz methods mfwdtran minvtran nm2deg nm2km nm2sm not notify null numden
onCleanup or orderfields orth pad parse partfrac pascal pcolor pinv planerot polar polarplot poly poly2sym polyder
polyint polyjoin pow2 pretty projfwd projinv properties psi rad2km rats rcond readcell readgeoraster readlines
readmatrix readtable reallog registerApp removecats removeCustomBasemap reordercats rescale rhs roots round
rows2vars rref runStartupFcn schur series setenv sgtitle shading shapeinfo simplify simplifyFraction sm2deg sm2km
sm2nm split splitlines splitvars sprand sprandn sqrtm stairs stem stem3 strip strjust strlength strtok struct2cell
struct2table subplot subs subtitle summary suptitle surf surface surfc surfl svds sym2poly symprod symsum
table2array table2cell table2struct table2timetable tail taylor timetable2table toeplitz trace transpose tril triu
type uminus unitsratio unmkpp uplus values vander vartype vecnorm vpa waterfall weekday which width wilkinson
worldmap worldToIntrinsic wrapTo180 wrapTo2Pi wrapTo360 wrapToPi writecell writematrix writetable yyaxis zeta ztrans
""".split():
    MIN_INPUTS[_n] = 1
for _n in """
addcats addCause addlistener addvars ancestor antipode areaint atan2d azimuth base2dec besselh beta betaln contourm
count deconv deval discretize distance ellipj endsWith erase extractAfter extractBefore filter2 funm geobubble
geoplot geoscatter givens groupsummary has histogram2 innerjoin ipermute iscategory isKey ismethod isolate ispolycw
isprop isstrprop legendre linsolve listener makima matches mergecats mergevars meridianarc mldivide movevars
mrdivide narginchk nargoutchk odeget optimget outerjoin polarscatter poly2ccw poly2cw polyarea polysplit polyvalm
ppval prctile quiver quiver3 realpow regexptranslate remove removevars renamecats retime rowfun scatter setcats
shapewrite startsWith synchronize timerange typecast validatestring varfun writelines
""".split():
    MIN_INPUTS[_n] = 2
for _n in """
aer2enu convertvars ecef2geodetic enu2aer extractBetween geodetic2ecef insertAfter insertBefore interpm ned2aer
optimplotconstrviolation optimplotfirstorderopt optimplotfunccount optimplotfval optimplotresnorm optimplotstepsize
optimplotx quadgk renamevars scatter3 setfield track1
""".split():
    MIN_INPUTS[_n] = 3
for _n in """
aer2ecef aer2geodetic areaquad ecef2aer ecef2enu ecef2ned ellipsoid enu2ecef enu2geodetic gcwaypts geodetic2aer
geodetic2enu geodetic2ned geointerp griddata inpolygon ned2ecef ned2geodetic polyxpoly reckon track2
""".split():
    MIN_INPUTS[_n] = 4
for _n in """
dblquad integral2 quad2d
""".split():
    MIN_INPUTS[_n] = 5
for _n in """
integral3 triplequad
""".split():
    MIN_INPUTS[_n] = 7

def _checked(info, k):
    """info's function with the count checked first (the workspace and nargout
    come before the inputs)."""
    fn, name = info.fn, info.name
    skip = 2 if info.ws else 1

    if info.aw:
        async def f(*a):
            if len(a) - skip < k:
                raise err('MATLAB:minrhs', 'Not enough input arguments.', name)
            return await fn(*a)
    else:
        def f(*a):
            if len(a) - skip < k:
                raise err('MATLAB:minrhs', 'Not enough input arguments.', name)
            return fn(*a)
    return f


def apply(reg):
    from . import Info
    for name, k in MIN_INPUTS.items():
        info = reg.get(name)
        if info is not None:
            reg[name] = Info(info.name, _checked(info, k), info.ws, info.aw, info.nout, info.arr)
