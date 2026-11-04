"""Partial differential equations in 2-D by finite elements: createpde,
geometryFromEdges, generateMesh, specifyCoefficients, applyBoundaryCondition,
setInitialConditions, solvepde (stationary, nonlinear by fixed-point
iteration, time-dependent by variable-step BDF2), solvepdeeig,
assembleFEMatrices, the results (interpolateSolution, evaluateGradient)
and pdeplot.

The equation is m*u'' + d*u' - div(c*grad(u)) + a*u = f on each face, u
having N components; Dirichlet conditions h*u = r (or u given) and
generalized Neumann conditions n.(c*grad(u)) + q*u = g on the edges.
Elements are triangles with 3 or 6 nodes, isoparametric (the curved sides
of quadratic elements follow the edges), integrated by a 6-point rule of
degree 4."""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, darr, out, is_str
from ..values import MError, Obj, Char, Cell, Struct, FH, Sparse, numel, py_str, EMPTY
from .. import runtime as R
from . import pdegeom as PG


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'pde:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


# ---- the reference elements ---------------------------------------------------------------------------------------------------

_A, _WA = 0.445948490915965, 0.223381589678011
_B, _WB = 0.091576213509771, 0.109951743655322
_QP = np.array([[_A, _A], [1 - 2 * _A, _A], [_A, 1 - 2 * _A], [_B, _B], [1 - 2 * _B, _B], [_B, 1 - 2 * _B]])
_QW = 0.5 * np.array([_WA, _WA, _WA, _WB, _WB, _WB])
_REF = {}


def _shape(order, xi, eta):
    """The basis functions and their derivatives at (xi, eta): N (n, nb), dN (n, nb, 2)."""
    xi, eta = np.asarray(xi, float), np.asarray(eta, float)
    L1, L2, L3 = 1 - xi - eta, xi, eta
    one = np.ones_like(xi)
    if order == 'linear':
        N = np.column_stack([L1, L2, L3])
        dN = np.stack([np.column_stack([-one, one, 0 * one]), np.column_stack([-one, 0 * one, one])], axis=2)
        return N, dN
    N = np.column_stack([L1 * (2 * L1 - 1), L2 * (2 * L2 - 1), L3 * (2 * L3 - 1), 4 * L1 * L2, 4 * L2 * L3, 4 * L3 * L1])
    dxi = np.column_stack([-(4 * L1 - 1), 4 * L2 - 1, 0 * one, 4 * (L1 - L2), 4 * L3, -4 * L3])
    deta = np.column_stack([-(4 * L1 - 1), 0 * one, 4 * L3 - 1, -4 * L2, 4 * L2, 4 * (L1 - L3)])
    return N, np.stack([dxi, deta], axis=2)


def _ref(order):
    if order not in _REF:
        N, dN = _shape(order, _QP[:, 0], _QP[:, 1])
        _REF[order] = {'N': N, 'dN': dN, 'w': _QW}
    return _REF[order]


class _Geo:
    """The elements' maps at the quadrature points: weights, gradients of the basis, the points."""

    def __init__(self, mesh):
        G = _ref(mesh.order)
        X = mesh.p[mesh.t]                                  # (ne, nb, 2)
        J = np.einsum('qbd,ebx->eqxd', G['dN'], X)          # dx/dxi: (ne, nq, x, d)
        det = J[..., 0, 0] * J[..., 1, 1] - J[..., 0, 1] * J[..., 1, 0]
        inv = np.empty_like(J)
        inv[..., 0, 0], inv[..., 1, 1] = J[..., 1, 1] / det, J[..., 0, 0] / det
        inv[..., 0, 1], inv[..., 1, 0] = -J[..., 0, 1] / det, -J[..., 1, 0] / det
        self.grad = np.einsum('qbd,eqdx->eqbx', G['dN'], inv)   # (ne, nq, nb, 2)
        self.W = G['w'][None, :] * np.abs(det)              # (ne, nq)
        self.N = G['N']                                     # (nq, nb)
        self.X = np.einsum('qb,ebx->eqx', G['N'], X)        # (ne, nq, 2)


# ---- the model ----------------------------------------------------------------------------------------------------------------------

class Options(Obj):
    cls = 'pde.PDESolverOptions'
    is_handle = True
    NAMES = ('AbsoluteTolerance', 'RelativeTolerance', 'ResidualTolerance', 'MaxIterations', 'MinStep', 'ResidualNorm', 'ReportStatistics')

    def __init__(self):
        self.v = {'AbsoluteTolerance': 1e-6, 'RelativeTolerance': 1e-3, 'ResidualTolerance': 1e-4, 'MaxIterations': 30.0,
                  'MinStep': 1.5e-8, 'ResidualNorm': 'Inf', 'ReportStatistics': 'off'}

    def getprop(self, name):
        k = next((n for n in self.NAMES if n.lower() == name.lower()), None)
        if k is None:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'PDESolverOptions'.")
        v = self.v[k]
        return Char.of(v) if isinstance(v, str) else float(v)

    def setprop(self, name, value):
        k = next((n for n in self.NAMES if n.lower() == name.lower()), None)
        if k is None:
            raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class 'PDESolverOptions'.")
        self.v[k] = py_str(value) if is_str(value) else float(np.asarray(darr(value)).reshape(-1)[0])

    def propnames(self):
        return list(self.NAMES)

    def display_lines(self):
        return ['  PDESolverOptions with properties:', ''] + [f'    {k:>17}: {v if isinstance(v, str) else f"{v:g}"}' for k, v in self.v.items()]


class Assignment(Obj):
    """A coefficient assignment, a boundary condition or initial conditions, as the functions return them."""
    is_handle = True

    def __init__(self, cls, props):
        self.cls_ = cls
        self.props = props

    @property
    def cls(self):
        return self.cls_

    def getprop(self, name):
        k = next((n for n in self.props if n.lower() == name.lower()), None)
        if k is None:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls_}'.")
        v = self.props[k]
        if v is None:
            return EMPTY()
        if isinstance(v, str):
            return Char.of(v)
        if isinstance(v, np.ndarray):
            return out(v)
        return v

    def propnames(self):
        return list(self.props)

    def display_lines(self):
        lines = [f'  {self.cls_.split(".")[-1]} with properties:', '']
        w = max(len(k) for k in self.props)
        for k, v in self.props.items():
            if v is None:
                s = '[]'
            elif isinstance(v, str):
                s = f"'{v}'"
            elif isinstance(v, FH):
                s = v.text()
            elif isinstance(v, np.ndarray):
                s = (f'{float(v.reshape(-1)[0]):g}' if v.size == 1 else '[' + ' '.join(f'{x:g}' for x in v.reshape(-1)[:8]) + (' ...]' if v.size > 8 else ']'))
            else:
                s = f'{v:g}' if isinstance(v, float) else str(v)
            lines.append(f'    {k:>{w}}: {s}')
        return lines


class PDEModel(Obj):
    cls = 'pde.PDEModel'
    is_handle = True

    def __init__(self, N):
        self.N = N
        self.geometry = None
        self.mesh = None
        self.coefs = []           # [(faces or None, {m, d, c, a, f})]
        self.bcs = []             # [dict]
        self.ics = []             # [(faces or None, u0, ut0)]
        self.opts = Options()

    def time_dependent(self):
        for _, co in self.coefs:
            for k in ('m', 'd'):
                v = co[k]
                if isinstance(v, FH) or np.any(np.asarray(v) != 0):
                    return True
        return False

    def hyperbolic(self):
        return any(isinstance(co['m'], FH) or np.any(np.asarray(co['m']) != 0) for _, co in self.coefs)

    def getprop(self, name):
        k = name.lower()
        if k == 'pdesystemsize':
            return float(self.N)
        if k == 'istimedependent':
            return self.time_dependent()
        if k == 'geometry':
            return self.geometry if self.geometry is not None else EMPTY()
        if k == 'mesh':
            return PG.FEMesh(self.mesh) if self.mesh is not None else EMPTY()
        if k == 'solveroptions':
            return self.opts
        if k == 'equationcoefficients':
            return Struct.scalar({'CoefficientAssignments': Cell.of_list([c for c in self._records('coef')], (1, len(self.coefs)))}) if self.coefs else EMPTY()
        if k == 'boundaryconditions':
            return Struct.scalar({'BoundaryConditionAssignments': Cell.of_list(self._records('bc'), (1, len(self.bcs)))}) if self.bcs else EMPTY()
        if k == 'initialconditions':
            return Struct.scalar({'InitialConditionAssignments': Cell.of_list(self._records('ic'), (1, len(self.ics)))}) if self.ics else EMPTY()
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'PDEModel'.")

    def _records(self, kind):
        if kind == 'coef':
            return [_coef_record(f, co) for f, co in self.coefs]
        if kind == 'bc':
            return [_bc_record(b) for b in self.bcs]
        return [Assignment('pde.GeometricInitialConditions', {'RegionType': 'face', 'RegionID': None if f is None else np.array(f, float),
                                                              'InitialValue': u0, 'InitialDerivative': ut0}) for f, u0, ut0 in self.ics]

    def setprop(self, name, value):
        k = name.lower()
        if k == 'geometry':
            if not isinstance(value, PG.Geometry):
                raise err('pde:PDEModel:Geometry', 'Geometry is set by geometryFromEdges.', 'PDEModel')
            self.geometry, self.mesh = value, None
            return
        if k == 'mesh' and isinstance(value, PG.FEMesh):
            self.mesh = value.m
            return
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{name}' property of PDEModel.")

    def propnames(self):
        return ['PDESystemSize', 'IsTimeDependent', 'Geometry', 'EquationCoefficients', 'BoundaryConditions', 'InitialConditions', 'Mesh', 'SolverOptions']

    def display_lines(self):
        def has(v, word):
            return f'[1×1 {word}]' if v else '[]'
        return ['  PDEModel with properties:', '', f'           PDESystemSize: {self.N}', f'         IsTimeDependent: {int(self.time_dependent())}',
                f'                Geometry: {has(self.geometry is not None, "AnalyticGeometry")}',
                f'    EquationCoefficients: {has(self.coefs, "CoefficientAssignmentRecords")}',
                f'      BoundaryConditions: {has(self.bcs, "BoundaryConditionsRecords")}',
                f'       InitialConditions: {has(self.ics, "InitialConditionsRecords")}',
                f'                    Mesh: {has(self.mesh is not None, "FEMesh")}', '           SolverOptions: [1×1 pde.PDESolverOptions]']


def _coef_record(faces, co):
    return Assignment('pde.CoefficientAssignment', {'RegionType': 'face', 'RegionID': None if faces is None else np.array(faces, float),
                                                    'm': co['m'], 'd': co['d'], 'c': co['c'], 'a': co['a'], 'f': co['f']})


def _bc_record(b):
    props = {'BCType': b['type'], 'RegionType': 'Edge', 'RegionID': np.array(b['edges'], float) + 1}
    for k in ('r', 'h', 'g', 'q', 'u', 'EquationIndex'):
        props[k] = b.get(k)
    props['Vectorized'] = 'off'
    return Assignment('pde.BoundaryCondition', props)


def _model(v, fn):
    if not isinstance(v, PDEModel):
        raise err(f'pde:{fn}:model', f'{fn} takes a PDE model (createpde).', fn)
    return v


@bi('createpde')
def createpde(nargout, *args):
    """model = createpde(), createpde(N): a model for a system of N (1) partial differential equations in 2-D."""
    nargchk(args, 0, 2, 'createpde')
    if args and is_str(args[0]):
        raise err('pde:createpde:type', f"'{py_str(args[0])}' models are not made here: createpde makes general PDE models (createpde(N)).", 'createpde')
    N = int(round(float(np.asarray(darr(args[0])).reshape(-1)[0]))) if args else 1
    if N < 1:
        raise err('pde:createpde:N', 'N is a whole number from 1.', 'createpde')
    return PDEModel(N)


@bi('geometryFromEdges')
def geometryFromEdges(nargout, *args):
    """gm = geometryFromEdges(model, g): the model's geometry from a decomposed geometry matrix (decsg) or a geometry function (a handle or a name: fun() the number of edges, fun(bs) their parameter ranges and faces, [x, y] = fun(bs, s) their points)."""
    nargchk(args, 2, 2, 'geometryFromEdges')
    m = _model(args[0], 'geometryFromEdges')
    g = PG.geometry_from(args[1])
    m.geometry, m.mesh = g, None
    return g


@bi('generateMesh')
def generateMesh(nargout, *args):
    """mesh = generateMesh(model, 'Hmax', h, 'Hmin', h, 'GeometricOrder', 'quadratic'): the model's triangular mesh: nodes along the edges about Hmax apart (a tenth of the geometry's size unless given; arcs in steps of at most 30 degrees), an equilateral lattice inside, a Delaunay triangulation that keeps every edge (pieces split until no node lies in another's diametral circle), smoothed; quadratic elements (default) have midside nodes, on the curve along an edge."""
    nargchk(args, 1, 11, 'generateMesh')
    m = _model(args[0], 'generateMesh')
    if m.geometry is None:
        raise err('pde:generateMesh:noGeometry', 'The model has no geometry: geometryFromEdges first.', 'generateMesh')
    o = PG._opts(list(args[1:]), ('hmax', 'hmin', 'hgrad', 'geometricorder', 'hedge', 'hvertex', 'hface'), 'generateMesh')
    if any(k in o for k in ('hedge', 'hvertex', 'hface')):
        raise err('pde:generateMesh:local', 'Hedge, Hvertex and Hface are not taken here: one size, Hmax, for the whole mesh.', 'generateMesh')
    hmax = float(np.asarray(darr(o['hmax'])).reshape(-1)[0]) if 'hmax' in o else None
    hmin = float(np.asarray(darr(o['hmin'])).reshape(-1)[0]) if 'hmin' in o else None
    order = py_str(o['geometricorder']).lower() if 'geometricorder' in o else 'quadratic'
    if order not in ('linear', 'quadratic'):
        raise err('pde:generateMesh:order', "GeometricOrder is 'linear' or 'quadratic'.", 'generateMesh')
    if hmax is not None and not hmax > 0:
        raise err('pde:generateMesh:Hmax', 'Hmax must be positive.', 'generateMesh')
    m.mesh = PG.make_mesh(m.geometry, hmax, hmin, order)
    return PG.FEMesh(m.mesh)


def _faces_arg(o, m, fn):
    if 'face' not in o:
        return None
    ids = [int(x) for x in np.asarray(darr(o['face']), float).reshape(-1)]
    nf = m.geometry.nfaces if m.geometry is not None else max(ids)
    if any(i < 1 or i > nf for i in ids):
        raise err(f'pde:{fn}:Face', f'The faces are numbered 1 to {nf}.', fn)
    return ids


def _coef_value(v, name, N, fn):
    if isinstance(v, FH):
        return v
    a = np.asarray(darr(v), float)
    if a.size == 0:
        return np.zeros(1)
    ok = {'c': (1, 2, 3, 4) if N == 1 else (1, N), 'f': (1, N), 'm': (1, N, N * N), 'd': (1, N, N * N), 'a': (1, N, N * N)}[name]
    if a.size not in ok:
        raise err(f'pde:{fn}:size', f"The coefficient {name} has {' or '.join(str(x) for x in sorted(set(ok)))} values here (or is a function handle).", fn)
    return a.reshape(-1, order='F')


@bi('specifyCoefficients')
def specifyCoefficients(nargout, *args):
    """CA = specifyCoefficients(model, 'm', m, 'd', d, 'c', c, 'a', a, 'f', f, 'Face', ids): the coefficients of m*u'' + d*u' - div(c*grad(u)) + a*u = f, all five given (0 for a term that is not there), on the faces (all unless given); a later assignment replaces an earlier one where they meet. Each is a number (c also [c11 c22], [c11 c12 c22] or [c11 c21 c12 c22] for one equation, a value for each equation for several; a, d and m a value for each or an N-by-N matrix; f a value for each equation), or a function handle of (location, state): location.x, .y, .subdomain, state.u, .ux, .uy, .time, giving a column for each point."""
    nargchk(args, 1, 13, 'specifyCoefficients')
    m = _model(args[0], 'specifyCoefficients')
    o = PG._opts(list(args[1:]), ('m', 'd', 'c', 'a', 'f', 'face'), 'specifyCoefficients')
    missing = [k for k in 'mdcaf' if k not in o]
    if missing:
        raise err('pde:specifyCoefficients:missing', f"All five coefficients are given: {', '.join(missing)} missing.", 'specifyCoefficients')
    co = {k: _coef_value(o[k], k, m.N, 'specifyCoefficients') for k in 'mdcaf'}
    faces = _faces_arg(o, m, 'specifyCoefficients')
    m.coefs.append((faces, co))
    return _coef_record(faces, co)


def _bc_value(v, name):
    if isinstance(v, FH):
        return v
    return np.asarray(darr(v), float).reshape(-1, order='F')


@bi('applyBoundaryCondition')
def applyBoundaryCondition(nargout, *args):
    """bc = applyBoundaryCondition(model, 'dirichlet', 'Edge', ids, 'u', u, 'EquationIndex', i), (..., 'dirichlet', 'Edge', ids, 'r', r, 'h', h), (..., 'neumann', 'Edge', ids, 'g', g, 'q', q), (..., 'mixed', 'Edge', ids, 'u', u, 'EquationIndex', i, 'g', g, 'q', q): a condition on edges of the boundary: Dirichlet h*u = r (h diagonal), or u given (for the components EquationIndex); generalized Neumann n.(c*grad(u)) + q*u = g. Values are numbers or function handles of (location, state) with location.x, .y, .nx, .ny and state.u, .time. An edge with no condition has g = q = 0."""
    nargchk(args, 3, 16, 'applyBoundaryCondition')
    m = _model(args[0], 'applyBoundaryCondition')
    rest = list(args[1:])
    kind = None
    if is_str(rest[0]) and py_str(rest[0]).lower() in ('dirichlet', 'neumann', 'mixed'):
        kind = py_str(rest.pop(0)).lower()
    o = PG._opts(rest, ('edge', 'face', 'u', 'r', 'h', 'g', 'q', 'equationindex', 'vectorized'), 'applyBoundaryCondition')
    if 'face' in o:
        raise err('pde:applyBoundaryCondition:Face', 'Conditions go on edges in 2-D.', 'applyBoundaryCondition')
    if 'edge' not in o:
        raise err('pde:applyBoundaryCondition:Edge', "The edges are given: 'Edge', ids.", 'applyBoundaryCondition')
    if kind is None:
        kind = 'dirichlet' if any(k in o for k in ('u', 'r', 'h')) else 'neumann'
    edges = [int(x) - 1 for x in np.asarray(darr(o['edge']), float).reshape(-1)]
    if m.geometry is not None:
        ne = len(m.geometry.curves)
        for e in edges:
            if e < 0 or e >= ne:
                raise err('pde:applyBoundaryCondition:Edge', f'The edges are numbered 1 to {ne}.', 'applyBoundaryCondition')
            if m.geometry.left[e] and m.geometry.right[e]:
                raise err('pde:applyBoundaryCondition:inner', f'Edge {e + 1} lies between two faces: conditions go on the outer edges.', 'applyBoundaryCondition')
    b = {'type': kind, 'edges': edges}
    for k in ('u', 'r', 'h', 'g', 'q'):
        if k in o:
            b[k] = _bc_value(o[k], k)
    if 'equationindex' in o:
        b['EquationIndex'] = np.asarray(darr(o['equationindex']), float).reshape(-1)
    if kind == 'dirichlet' and not any(k in b for k in ('u', 'r')):
        raise err('pde:applyBoundaryCondition:dirichlet', "A Dirichlet condition gives u, or r (and h).", 'applyBoundaryCondition')
    if kind == 'mixed' and 'u' not in b and 'r' not in b:
        raise err('pde:applyBoundaryCondition:mixed', 'A mixed condition gives u (with EquationIndex) and g or q.', 'applyBoundaryCondition')
    m.bcs.append(b)
    return _bc_record(b)


@bi('setInitialConditions')
def setInitialConditions(nargout, *args):
    """IC = setInitialConditions(model, u0), (model, u0, ut0), (..., 'Face', ids), (model, results): the initial values (and, for m ~= 0, the initial rate) of a time-dependent or nonlinear problem: numbers, a function handle of location (location.x, .y, .subdomain), or the last solution of results."""
    nargchk(args, 2, 5, 'setInitialConditions')
    m = _model(args[0], 'setInitialConditions')
    rest = list(args[1:])
    faces = None
    if len(rest) >= 2 and is_str(rest[-2]) and py_str(rest[-2]).lower() == 'face':
        faces = [int(x) for x in np.asarray(darr(rest[-1]), float).reshape(-1)]
        rest = rest[:-2]
    u0 = rest[0]
    if isinstance(u0, _Results):
        u0 = u0.last()
    elif not isinstance(u0, FH):
        u0 = np.asarray(darr(u0), float)
    ut0 = rest[1] if len(rest) > 1 else None
    if ut0 is not None and not isinstance(ut0, FH):
        ut0 = np.asarray(darr(ut0), float)
    m.ics.append((faces, u0, ut0))
    return Assignment('pde.GeometricInitialConditions', {'RegionType': 'face', 'RegionID': None if faces is None else np.array(faces, float),
                                                         'InitialValue': u0 if not isinstance(u0, np.ndarray) or u0.size <= 64 else None,
                                                         'InitialDerivative': ut0})


# ---- evaluating coefficients -------------------------------------------------------------------------------------------------------

def _loc_struct(fields):
    return Struct.scalar({k: out(np.asarray(v, float).reshape(1, -1)) for k, v in fields.items()})


def _call(fh, loc, state, rows_ok, npts, name):
    """A coefficient's function handle at npts points: its result as (rows, npts)."""
    st = Struct.scalar({k: (out(np.asarray(v, float)) if not isinstance(v, float) else v) for k, v in state.items()})
    r = fh.scall(1, _loc_struct(loc), st)
    a = np.asarray(darr(r), float)
    if a.size == 1:
        return np.full((1, npts), float(a.reshape(-1)[0]))
    a = a.reshape(-1, npts) if a.ndim == 2 and a.shape[1] == npts else a.reshape(a.shape[0] if a.ndim == 2 else 1, -1)
    if a.shape[1] != npts:
        raise err('pde:coefficient:size', f'The function for {name} must give a column for each of the {npts} points.', 'solvepde')
    return a


def _eval(spec, name, N, loc, state, npts):
    if isinstance(spec, FH):
        return _call(spec, loc, state, None, npts, name)
    return np.repeat(np.asarray(spec, float).reshape(-1, 1), npts, axis=1)


def _component_matrix(v, N):
    """A coefficient's values (rows, n) as N-by-N matrices at each point: (N, N, n)."""
    rows, n = v.shape
    M = np.zeros((N, N, n))
    if rows == 1:
        for k in range(N):
            M[k, k] = v[0]
    elif rows == N:
        for k in range(N):
            M[k, k] = v[k]
    elif rows == N * N:
        M = v.reshape(N, N, n, order='F')
    else:
        raise err('pde:coefficient:size', 'A coefficient has 1, N or N^2 values at each point.', 'solvepde')
    return M


# ---- assembly ---------------------------------------------------------------------------------------------------------------------------

class _System:
    """The model's mesh, the elements' maps, the assignments by face; assembles at a time and a state."""

    def __init__(self, model):
        if model.geometry is None:
            raise err('pde:solvepde:noGeometry', 'The model has no geometry: geometryFromEdges first.', 'solvepde')
        if model.mesh is None:
            raise err('pde:solvepde:noMesh', 'The model has no mesh: generateMesh first.', 'solvepde')
        if not model.coefs:
            raise err('pde:solvepde:noCoefficients', 'The model has no coefficients: specifyCoefficients first.', 'solvepde')
        self.model, self.mesh, self.N = model, model.mesh, model.N
        self.geo = _Geo(self.mesh)
        self.np = self.mesh.p.shape[0]
        self.ndof = self.np * self.N
        nf = model.geometry.nfaces
        which = np.full(nf + 1, -1)
        for k, (faces, _) in enumerate(model.coefs):
            for f in (range(1, nf + 1) if faces is None else faces):
                which[f] = k
        if np.any(which[1:] < 0):
            missing = [str(f) for f in range(1, nf + 1) if which[f] < 0]
            raise err('pde:solvepde:faceCoefficients', f"Face{'s' if len(missing) > 1 else ''} {', '.join(missing)} {'have' if len(missing) > 1 else 'has'} no coefficients.", 'solvepde')
        self.elem_coef = which[self.mesh.tface]
        used = set(int(k) for k in np.unique(self.elem_coef))
        self.nonlinear = any(isinstance(v, FH) for k, (_, co) in enumerate(model.coefs) if k in used for v in co.values()) or \
            any(isinstance(v, FH) for b in model.bcs for k, v in b.items() if k in ('g', 'q', 'u', 'r', 'h'))
        self._cache = {}

    # the solution's values and gradients at the quadrature points
    def state_q(self, U, els):
        t = self.mesh.t[els]
        if U is None:
            z = np.zeros((self.N, els.size * self.geo.N.shape[0]))
            return z, z, z
        u = np.einsum('qb,ebk->keq', self.geo.N, U[t]).reshape(self.N, -1)
        g = np.einsum('eqbx,ebk->kexq', self.geo.grad[els], U[t])
        return u, g[:, :, 0, :].reshape(self.N, -1), g[:, :, 1, :].reshape(self.N, -1)

    def coefs_at(self, k, name, t, U):
        """Coefficient name of assignment k at the quadrature points of its elements: (elements, values (rows, nel*nq))."""
        els = np.flatnonzero(self.elem_coef == k)
        spec = self.model.coefs[k][1][name]
        nq = self.geo.N.shape[0]
        npts = els.size * nq
        if els.size == 0:
            return els, np.zeros((1, 0))
        if not isinstance(spec, FH):
            return els, np.asarray(spec, float).reshape(-1, 1) * np.ones((1, npts))
        X = self.geo.X[els].reshape(-1, 2)
        u, ux, uy = self.state_q(U, els)
        loc = {'x': X[:, 0], 'y': X[:, 1], 'subdomain': np.repeat(self.mesh.tface[els], nq)}
        state = {'u': u, 'ux': ux, 'uy': uy, 'time': float(t)}
        return els, _eval(spec, name, self.N, loc, state, npts)

    def _scatter(self, rows, cols, vals):
        from scipy import sparse
        return sparse.csr_matrix((vals.ravel(), (rows.ravel(), cols.ravel())), shape=(self.ndof, self.ndof))

    def matrices(self, t=0.0, U=None, which='mdcaf'):
        """The domain matrices and load: {'m', 'd', 'c' (stiffness), 'a', 'f'} at time t and state U (np, N)."""
        key = (which,) if not self.nonlinear else None
        if key is not None and key in self._cache:
            return self._cache[key]
        from scipy import sparse
        N, npn = self.N, self.np
        res = {k: sparse.csr_matrix((self.ndof, self.ndof)) for k in which if k != 'f'}
        F = np.zeros(self.ndof)
        G = self.geo
        nq, nb = G.N.shape
        for k in range(len(self.model.coefs)):
            for name in which:
                els, v = self.coefs_at(k, name, t, U)
                if els.size == 0:
                    continue
                tt = self.mesh.t[els]
                W = G.W[els]
                if name == 'f':
                    v = np.repeat(v, N, axis=0) if v.shape[0] == 1 and N > 1 else v
                    if v.shape[0] != N:
                        raise err('pde:coefficient:size', 'f has a value for each equation.', 'solvepde')
                    for c in range(N):
                        fq = v[c].reshape(els.size, nq) * W
                        Fe = np.einsum('eq,qb->eb', fq, G.N)
                        np.add.at(F, tt.ravel() + c * npn, Fe.ravel())
                    continue
                if name == 'c':
                    mats = self._stiffness(els, tt, v, W)
                else:
                    Mk = _component_matrix(v, N)
                    mats = []
                    for i in range(N):
                        for j in range(N):
                            cq = Mk[i, j].reshape(els.size, nq)
                            if not np.any(cq):
                                continue
                            Ke = np.einsum('eq,qa,qb->eab', cq * W, G.N, G.N)
                            mats.append((i, j, Ke))
                for i, j, Ke in mats:
                    rows = (tt[:, :, None] + i * npn) * np.ones((1, 1, nb), int)
                    cols = (tt[:, None, :] + j * npn) * np.ones((1, nb, 1), int)
                    res[name] = res[name] + self._scatter(rows, cols, Ke)
        out_ = dict(res)
        if 'f' in which:
            out_['f'] = F
        if key is not None:
            self._cache[key] = out_
        return out_

    def _stiffness(self, els, tt, v, W):
        G = self.geo
        nq = G.N.shape[0]
        gr = G.grad[els]                              # (e, q, b, 2)
        N = self.N
        mats = []
        if N == 1:
            rows = v.shape[0]
            c = [x.reshape(els.size, nq) for x in v]
            if rows == 1:
                C = [[c[0], 0], [0, c[0]]]
            elif rows == 2:
                C = [[c[0], 0], [0, c[1]]]
            elif rows == 3:
                C = [[c[0], c[1]], [c[1], c[2]]]
            elif rows == 4:
                C = [[c[0], c[2]], [c[1], c[3]]]
            else:
                raise err('pde:coefficient:size', 'c has 1, 2, 3 or 4 values at each point for one equation.', 'solvepde')
            Ke = 0
            for x in range(2):
                for y in range(2):
                    cxy = C[x][y]
                    if isinstance(cxy, int):
                        continue
                    Ke = Ke + np.einsum('eq,eqa,eqb->eab', cxy * W, gr[..., x], gr[..., y])
            mats.append((0, 0, Ke))
            return mats
        cv = v if v.shape[0] in (1, N) else None
        if cv is None:
            raise err('pde:coefficient:size', 'c has 1 or N values at each point for a system (each equation isotropic).', 'solvepde')
        for i in range(N):
            ci = cv[0 if cv.shape[0] == 1 else i].reshape(els.size, nq)
            Ke = np.einsum('eq,eqax,eqbx->eab', ci * W, gr, gr)
            mats.append((i, i, Ke))
        return mats

    # ---- the boundary ----
    def boundary(self, t=0.0, U=None):
        """Q, G from the Neumann parts of the conditions; Dirichlet values: (dofs, values)."""
        if not self.nonlinear and 'boundary' in self._cache:
            return self._cache['boundary']
        res = self._boundary(t, U)
        if not self.nonlinear:
            self._cache['boundary'] = res
        return res

    def _boundary(self, t, U):
        from scipy import sparse
        N, npn = self.N, self.np
        mesh, geom = self.mesh, self.model.geometry
        Q = sparse.csr_matrix((self.ndof, self.ndof))
        Gv = np.zeros(self.ndof)
        cons = {}
        # the last condition given on an edge is the one that holds
        on = {}
        for b in self.model.bcs:
            for e in b['edges']:
                on[e] = b
        gs = np.array([0.5 - math.sqrt(15) / 10, 0.5, 0.5 + math.sqrt(15) / 10])
        gw = np.array([5, 8, 5]) / 18.0
        quad = mesh.order == 'quadratic'
        if quad:
            Nl = np.column_stack([(1 - gs) * (1 - 2 * gs), 4 * gs * (1 - gs), gs * (2 * gs - 1)])
            dNl = np.column_stack([4 * gs - 3, 4 - 8 * gs, 4 * gs - 1])
        else:
            Nl = np.column_stack([1 - gs, gs])
            dNl = np.column_stack([-np.ones(3), np.ones(3)])
        by_bc = {}
        for a, bnode, mid, e in mesh.bsegs:
            b = on.get(e)
            if b is None:
                continue
            by_bc.setdefault(id(b), (b, []))[1].append((a, mid, bnode, e) if quad else (a, bnode, e))
        dir_nodes = []
        for b, pieces in by_bc.values():
            kind = b['type']
            idx = [int(i) - 1 for i in b.get('EquationIndex', np.arange(1, N + 1))]
            dcomp = [] if kind == 'neumann' else idx
            ncomp = list(range(N)) if kind == 'neumann' else ([k for k in range(N) if k not in idx] if kind == 'mixed' else [])
            if ncomp and ('g' in b or 'q' in b):
                nodes = np.array([pc[:-1] for pc in pieces], int)       # (npc, nl)
                edges_of = np.array([pc[-1] for pc in pieces], int)
                X = mesh.p[nodes]                                      # (npc, nl, 2)
                XQ = np.einsum('qb,ebx->eqx', Nl, X)
                T = np.einsum('qb,ebx->eqx', dNl, X)
                ds = np.hypot(T[..., 0], T[..., 1])
                inside_left = geom.left[edges_of] != 0
                nx = np.where(inside_left[:, None], T[..., 1], -T[..., 1]) / ds
                ny = np.where(inside_left[:, None], -T[..., 0], T[..., 0]) / ds
                W = ds * gw[None, :]
                npts = XQ.shape[0] * 3
                loc = {'x': XQ[..., 0].ravel(), 'y': XQ[..., 1].ravel(), 'nx': nx.ravel(), 'ny': ny.ravel()}
                if U is not None:
                    uq = np.einsum('qb,ebk->keq', Nl, U[nodes]).reshape(N, -1)
                else:
                    uq = np.zeros((N, npts))
                state = {'u': uq, 'time': float(t)}
                if 'g' in b:
                    gv = _eval(b['g'], 'g', N, loc, state, npts)
                    gv = np.repeat(gv, N, axis=0) if gv.shape[0] == 1 and N > 1 else gv
                    for c in ncomp:
                        ge = np.einsum('eq,qb->eb', gv[c].reshape(-1, 3) * W, Nl)
                        np.add.at(Gv, nodes.ravel() + c * npn, ge.ravel())
                if 'q' in b:
                    qv = _component_matrix(_eval(b['q'], 'q', N, loc, state, npts), N)
                    nl = nodes.shape[1]
                    for i in ncomp:
                        for j in ncomp:
                            qq = qv[i, j].reshape(-1, 3)
                            if not np.any(qq):
                                continue
                            Ke = np.einsum('eq,qa,qb->eab', qq * W, Nl, Nl)
                            rows = (nodes[:, :, None] + i * npn) * np.ones((1, 1, nl), int)
                            cols = (nodes[:, None, :] + j * npn) * np.ones((1, nl, 1), int)
                            Q = Q + self._scatter(rows, cols, Ke)
            if dcomp:
                nodes = sorted({int(x) for pc in pieces for x in pc[:-1] if x >= 0})
                dir_nodes.append((b, np.array(nodes, int), dcomp))
        for b, nodes, dcomp in dir_nodes:
            P = mesh.p[nodes]
            loc = {'x': P[:, 0], 'y': P[:, 1], 'nx': np.zeros(len(nodes)), 'ny': np.zeros(len(nodes))}
            state = {'u': (U[nodes].T if U is not None else np.zeros((N, len(nodes)))), 'time': float(t)}
            if 'u' in b:
                v = _eval(b['u'], 'u', N, loc, state, len(nodes))
                if v.shape[0] == 1 and len(dcomp) > 1:
                    v = np.repeat(v, len(dcomp), axis=0)
                if v.shape[0] == N and len(dcomp) < N:
                    v = v[dcomp]
                if v.shape[0] != len(dcomp):
                    raise err('pde:bc:size', 'u has a value for each component the condition sets (EquationIndex).', 'solvepde')
            else:
                r = _eval(b['r'], 'r', N, loc, state, len(nodes))
                r = np.repeat(r, N, axis=0) if r.shape[0] == 1 and N > 1 else r
                h = _component_matrix(_eval(b['h'], 'h', N, loc, state, len(nodes)), N) if 'h' in b else None
                if h is not None:
                    off = h.copy()
                    for k in range(N):
                        off[k, k] = 0
                    if np.any(off):
                        raise err('pde:bc:h', 'h is diagonal here (each component its own condition).', 'solvepde')
                    v = np.array([r[k] / h[k, k] for k in dcomp])
                else:
                    v = r[dcomp]
            for j, c in enumerate(dcomp):
                for nd, val in zip(nodes, v[j]):
                    cons[int(nd) + c * npn] = float(val)
        keys = np.array(sorted(cons), int)
        vals = np.array([cons[k] for k in keys], float)
        return Q, Gv, keys, vals

    def gradients(self, U):
        """Nodal gradients (np, N) of x and y: each node's average over the elements it belongs to."""
        mesh = self.mesh
        order = mesh.order
        ref_nodes = np.array([[0, 0], [1, 0], [0, 1], [0.5, 0], [0.5, 0.5], [0, 0.5]])[: mesh.t.shape[1]]
        _, dN = _shape(order, ref_nodes[:, 0], ref_nodes[:, 1])           # (nb, nb, 2) at each node
        X = mesh.p[mesh.t]
        J = np.einsum('nbd,ebx->enxd', dN, X)
        det = J[..., 0, 0] * J[..., 1, 1] - J[..., 0, 1] * J[..., 1, 0]
        inv = np.empty_like(J)
        inv[..., 0, 0], inv[..., 1, 1] = J[..., 1, 1] / det, J[..., 0, 0] / det
        inv[..., 0, 1], inv[..., 1, 0] = -J[..., 0, 1] / det, -J[..., 1, 0] / det
        gr = np.einsum('nbd,endx->enbx', dN, inv)                         # (e, at node n, of basis b, x)
        gx, gy = np.zeros((self.np, self.N)), np.zeros((self.np, self.N))
        cnt = np.zeros(self.np)
        for k in range(self.N):
            Uk = U[mesh.t, k]                                             # (e, b)
            vx = np.einsum('enb,eb->en', gr[..., 0], Uk)
            vy = np.einsum('enb,eb->en', gr[..., 1], Uk)
            np.add.at(gx[:, k], mesh.t.ravel(), vx.ravel())
            np.add.at(gy[:, k], mesh.t.ravel(), vy.ravel())
        np.add.at(cnt, mesh.t.ravel(), 1.0)
        return gx / cnt[:, None], gy / cnt[:, None]


def _initial(model, sysm, which=1):
    """The initial values (np, N) from setInitialConditions (zero where none)."""
    N, mesh = model.N, model.mesh
    U = np.zeros((mesh.p.shape[0], N))
    face_of_node = np.zeros(mesh.p.shape[0], int)
    face_of_node[mesh.t.ravel()] = np.repeat(mesh.tface, mesh.t.shape[1])
    for faces, u0, ut0 in model.ics:
        v = u0 if which == 1 else ut0
        if v is None:
            continue
        sel = np.ones(mesh.p.shape[0], bool) if faces is None else np.isin(face_of_node, faces)
        idx = np.flatnonzero(sel)
        if isinstance(v, FH):
            P = mesh.p[idx]
            r = v.scall(1, _loc_struct({'x': P[:, 0], 'y': P[:, 1], 'subdomain': face_of_node[idx]}))
            a = np.asarray(darr(r), float)
            a = a.reshape(-1, idx.size) if a.size != 1 else np.full((1, idx.size), float(a.reshape(-1)[0]))
            a = np.repeat(a, N, axis=0) if a.shape[0] == 1 else a
            U[idx] = a[:N].T
        else:
            a = np.asarray(v, float)
            if a.ndim >= 1 and a.shape[0] == mesh.p.shape[0]:
                U[idx] = a.reshape(mesh.p.shape[0], -1)[idx][:, :N] if a.size >= mesh.p.shape[0] * N else np.repeat(a.reshape(-1, 1)[idx], N, axis=1)
            else:
                vals = a.reshape(-1)
                U[idx] = np.broadcast_to(vals[:N] if vals.size >= N else np.repeat(vals[:1], N), (idx.size, N))
    return U


def _solve_stationary(model):
    S = _System(model)
    opts = model.opts.v
    U = _initial(model, S) if S.nonlinear else None
    maxit = int(opts['MaxIterations']) if S.nonlinear else 1
    tol = float(opts['ResidualTolerance'])
    it = 0
    for it in range(1, maxit + 1):
        mats = S.matrices(0.0, U, 'caf')
        Q, Gv, cd, cv = S.boundary(0.0, U)
        K = (mats['c'] + mats['a'] + Q).tocsr()
        F = mats['f'] + Gv
        u = _solve_constrained(K, F, cd, cv)
        Un = u.reshape(S.N, S.np).T
        if not S.nonlinear:
            U = Un
            break
        change = np.max(np.abs(Un - U)) / max(1.0, float(np.max(np.abs(Un)))) if U is not None else np.inf
        U = Un
        if change <= tol:
            break
    else:
        if S.nonlinear and maxit > 1:
            R.warn('pde:solvepde:notConverged', f'The fixed-point iteration did not converge in {maxit} iterations (MaxIterations).')
    gx, gy = S.gradients(U)
    return StationaryResults(model.mesh, U, gx, gy, model.N)


def _solve_constrained(K, F, cd, cv):
    n = F.size
    u = np.zeros(n)
    if cd.size:
        u[cd] = cv
    free = np.setdiff1d(np.arange(n), cd)
    rhs = F[free] - (K[free][:, cd] @ cv if cd.size else 0)
    import warnings
    from scipy.sparse.linalg import splu
    Kff = K[free][:, free].tocsc()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        try:
            lu = splu(Kff)
            piv = np.abs(lu.U.diagonal())
            singular = piv.size and piv.min() <= 1e-12 * piv.max()
            u[free] = lu.solve(rhs)
        except RuntimeError:
            singular = True
    if singular or not np.all(np.isfinite(u)):
        raise err('pde:solvepde:singular', 'The system is singular: a component with only Neumann conditions and no a term has no unique solution.', 'solvepde')
    return u


def _solve_time(model, tlist):
    """Variable-step BDF2 (backward Euler for the first step) on M y' + K y = F, each step within the tolerances; y = [u; u'] when m ~= 0."""
    from scipy import sparse
    from scipy.sparse.linalg import splu
    S = _System(model)
    opts = model.opts.v
    rtol, atol = float(opts['RelativeTolerance']), float(opts['AbsoluteTolerance'])
    hyper = model.hyperbolic()
    n = S.ndof
    which = 'mdcaf' if hyper else 'dcaf'

    def system(t, y):
        U = y[:n].reshape(S.N, S.np).T
        mats = S.matrices(t, U, which)
        Q, Gv, cd, cv = S.boundary(t, U)
        K = (mats['c'] + mats['a'] + Q).tocsr()
        F = mats['f'] + Gv
        if not hyper:
            return mats['d'].tocsr(), K, F, cd, cv
        # m u'' + d u' + K u = F as [u; v]' with v = u'
        I = sparse.identity(n, format='csr')
        M = sparse.bmat([[I, None], [None, mats['m']]], format='csr')
        A = sparse.bmat([[None, -I], [K, mats['d']]], format='csr')
        dt = 1e-6 * max(1.0, abs(t))
        cv2 = S.boundary(t + dt, U)[3]
        cv1 = S.boundary(t - dt, U)[3]
        rate = (cv2 - cv1) / (2 * dt) if cv2.size == cv.size == cv1.size else np.zeros(cv.size)
        return M, A, np.concatenate([np.zeros(n), F]), np.concatenate([cd, cd + n]), np.concatenate([cv, rate])

    t0, tf = float(tlist[0]), float(tlist[-1])
    y = _initial(model, S).T.reshape(-1)
    if hyper:
        y = np.concatenate([y, _initial(model, S, 2).T.reshape(-1)])
    _, _, _, cd, cv = system(t0, y)
    y[cd] = cv
    outs, ts = [y[:n].copy()], [t0]
    k_out, t = 1, t0
    h = (tf - t0) * 1e-4
    hist = []                                  # the last two accepted (t, y) before the current one
    steps = 0
    while k_out < len(tlist):
        target = float(tlist[k_out])
        if t + h >= target - 1e-12 * max(1.0, abs(target)):
            h = target - t
        tn = t + h
        if hist:
            tp, yp = hist[-1]
            w = h / (t - tp)
            a0, a1, a2 = (1 + 2 * w) / (1 + w), -(1 + w), w * w / (1 + w)
        else:
            a0, a1, a2, yp = 1.0, -1.0, 0.0, y

        def step(yguess):
            M, K, F, cd, cv = system(tn, yguess)
            free = np.setdiff1d(np.arange(y.size), cd)
            A = ((a0 / h) * M + K).tocsr()
            b = F - (M @ (a1 * y + a2 * yp)) / h
            yn = np.zeros_like(y)
            yn[cd] = cv
            rb = b[free] - (A[free][:, cd] @ cv if cd.size else 0)
            yn[free] = splu(A[free][:, free].tocsc()).solve(rb)
            return yn, free
        yn, free = step(y)
        if S.nonlinear:
            for _ in range(int(opts['MaxIterations'])):
                y2, free = step(yn)
                done = np.max(np.abs(y2 - yn)) <= 0.1 * (atol + rtol * float(np.max(np.abs(y2))))
                yn = y2
                if done:
                    break
        # the local error: the step against the polynomial through the last points, carried to tn
        if len(hist) >= 2:
            tq = np.array([hist[-2][0], hist[-1][0], t])
            Lg = [np.prod([(tn - tq[j]) / (tq[i] - tq[j]) for j in range(3) if j != i]) for i in range(3)]
            est = (2 / 11) * (yn - (Lg[0] * hist[-2][1] + Lg[1] * hist[-1][1] + Lg[2] * y))
        elif hist:
            est = (1 / 3) * (yn - (y + (tn - t) / (t - hist[-1][0]) * (y - hist[-1][1])))
        else:
            est = np.zeros_like(y)
        scale = atol + rtol * np.maximum(np.abs(y), np.abs(yn))
        e = float(np.max(np.abs(est[free]) / scale[free])) if free.size else 0.0
        steps += 1
        if steps > 200000:
            raise err('pde:solvepde:steps', 'Too many time steps: the problem may be too stiff or the tolerances too tight.', 'solvepde')
        if e > 1 and h > float(opts['MinStep']) * max(1.0, abs(t)):
            h *= max(0.2, 0.9 * e ** (-1 / 3))
            continue
        hist = (hist + [(t, y)])[-2:]
        t, y = tn, yn
        if abs(t - target) <= 1e-12 * max(1.0, abs(target)):
            outs.append(y[:n].copy())
            ts.append(t)
            k_out += 1
        h *= 2.0 if e == 0 else min(2.0, max(0.2, 0.9 * e ** (-1 / 3)))
        if len(hist) < 2:
            h = min(h, (tf - t0) * 1e-2)
    Us = np.stack([o.reshape(S.N, S.np).T for o in outs], axis=2)           # (np, N, nt)
    grads = [S.gradients(Us[:, :, k]) for k in range(Us.shape[2])]
    gx = np.stack([g[0] for g in grads], axis=2)
    gy = np.stack([g[1] for g in grads], axis=2)
    return TimeDependentResults(model.mesh, Us, gx, gy, np.array(ts), model.N)


@bi('solvepde')
def solvepde(nargout, *args):
    """results = solvepde(model), solvepde(model, tlist): the solution: stationary (a sparse direct solve; with coefficients or conditions that are functions, a fixed-point iteration from the initial conditions until the change is below SolverOptions.ResidualTolerance), or at the times tlist when m or d is not zero (variable-step BDF2 within SolverOptions' RelativeTolerance and AbsoluteTolerance; second order in time as a first-order system in u and u')."""
    nargchk(args, 1, 2, 'solvepde')
    m = _model(args[0], 'solvepde')
    if m.time_dependent():
        if len(args) < 2:
            raise err('pde:solvepde:tlist', 'A time-dependent problem (m or d not zero) needs the times: solvepde(model, tlist).', 'solvepde')
        tl = np.asarray(darr(args[1]), float).reshape(-1)
        if tl.size < 2 or np.any(np.diff(tl) <= 0):
            raise err('pde:solvepde:tlist', 'tlist is increasing times, at least two.', 'solvepde')
        return _solve_time(m, tl)
    if len(args) > 1:
        raise err('pde:solvepde:stationary', 'A stationary problem (m and d zero) takes no times.', 'solvepde')
    return _solve_stationary(m)


@bi('solvepdeeig')
def solvepdeeig(nargout, *args):
    """results = solvepdeeig(model, [lo hi]): the eigenvalues lambda in [lo, hi] of -div(c*grad(u)) + a*u = lambda*d*u (m = 0, f = 0) with the model's boundary conditions (Dirichlet ones zero), and their eigenvectors; by scipy.linalg.eigh on the reduced matrices, or scipy.sparse.linalg.eigsh shifted to lo for big ones."""
    nargchk(args, 2, 2, 'solvepdeeig')
    m = _model(args[0], 'solvepdeeig')
    rng = np.asarray(darr(args[1]), float).reshape(-1)
    if rng.size != 2 or not rng[1] > rng[0]:
        raise err('pde:solvepdeeig:range', 'The range is [lo hi], lo < hi (hi may be Inf).', 'solvepdeeig')
    S = _System(m)
    mats = S.matrices(0.0, None, 'dca')
    Q, _, cd, cv = S.boundary(0.0, None)
    K = (mats['c'] + mats['a'] + Q).tocsr()
    Mm = mats['d'].tocsr()
    free = np.setdiff1d(np.arange(S.ndof), cd)
    Kf, Mf = K[free][:, free], Mm[free][:, free]
    lo, hi = float(rng[0]), float(rng[1])
    if free.size <= 2500:
        from scipy.linalg import eigh
        w, V = eigh(Kf.toarray(), Mf.toarray())
        sel = (w >= lo) & (w <= hi)
        w, V = w[sel], V[:, sel]
    else:
        from scipy.sparse.linalg import eigsh
        k = 20
        while True:
            k = min(k, free.size - 2)
            w, V = eigsh(Kf.tocsc(), k=k, M=Mf.tocsc(), sigma=lo if np.isfinite(lo) else 0.0, which='LM')
            order = np.argsort(w)
            w, V = w[order], V[:, order]
            if w.max() > hi or k >= free.size - 2 or not np.isfinite(hi):
                break
            k *= 2
        sel = (w >= lo) & (w <= hi)
        w, V = w[sel], V[:, sel]
    full = np.zeros((S.ndof, w.size))
    full[free] = V
    vecs = np.stack([full[:, j].reshape(S.N, S.np).T for j in range(w.size)], axis=2) if w.size else np.zeros((S.np, S.N, 0))
    return EigenResults(m.mesh, vecs, w, m.N)


@bi('assembleFEMatrices')
def assembleFEMatrices(nargout, *args):
    """FEM = assembleFEMatrices(model): the finite-element matrices of a stationary problem: K (c), A (a), F (f), Q (q), G (g), H and R (the Dirichlet conditions as H*u = R, a row for each fixed value), M (m, or d when m is zero); sparse, the components of a system one after another."""
    nargchk(args, 1, 2, 'assembleFEMatrices')
    m = _model(args[0], 'assembleFEMatrices')
    from scipy import sparse
    S = _System(m)
    U = _initial(m, S) if S.nonlinear else None
    mats = S.matrices(0.0, U, 'mdcaf')
    Q, Gv, cd, cv = S.boundary(0.0, U)
    H = sparse.csr_matrix((np.ones(cd.size), (np.arange(cd.size), cd)), shape=(cd.size, S.ndof))
    Mm = mats['m'] if m.hyperbolic() else mats['d']
    sp = lambda A: Sparse(sparse.csc_matrix(A))  # noqa: E731
    return Struct.scalar({'K': sp(mats['c']), 'A': sp(mats['a']), 'F': out(mats['f'].reshape(-1, 1)), 'Q': sp(Q), 'G': out(Gv.reshape(-1, 1)),
                          'H': sp(H), 'R': out(cv.reshape(-1, 1)), 'M': sp(Mm)})


# ---- results --------------------------------------------------------------------------------------------------------------------------

class _Results(Obj):
    is_handle = False

    def value_copy(self):
        return self

    def mesh_prop(self):
        return PG.FEMesh(self.mesh)


def _sq(U, N):
    """A nodal array as the language shows it: np-by-1 (or by nt) for one equation."""
    if N == 1:
        return U[:, 0] if U.ndim == 2 else U[:, 0, :]
    return U


class StationaryResults(_Results):
    cls = 'pde.StationaryResults'

    def __init__(self, mesh, U, gx, gy, N):
        self.mesh, self.U, self.gx, self.gy, self.N = mesh, U, gx, gy, N

    def last(self):
        return self.U

    def getprop(self, name):
        k = name.lower()
        if k == 'nodalsolution':
            return out(np.atleast_2d(_sq(self.U, self.N)).reshape(self.U.shape[0], -1))
        if k == 'xgradients':
            return out(_sq(self.gx, self.N).reshape(self.U.shape[0], -1))
        if k == 'ygradients':
            return out(_sq(self.gy, self.N).reshape(self.U.shape[0], -1))
        if k == 'zgradients':
            return EMPTY()
        if k == 'mesh':
            return self.mesh_prop()
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'StationaryResults'.")

    def propnames(self):
        return ['NodalSolution', 'XGradients', 'YGradients', 'ZGradients', 'Mesh']

    def display_lines(self):
        npn = self.U.shape[0]
        sz = f'{npn}×1' if self.N == 1 else f'{npn}×{self.N}'
        return ['  StationaryResults with properties:', '', f'    NodalSolution: [{sz} double]', f'       XGradients: [{sz} double]',
                f'       YGradients: [{sz} double]', '       ZGradients: []', '             Mesh: [1×1 FEMesh]']


class TimeDependentResults(_Results):
    cls = 'pde.TimeDependentResults'

    def __init__(self, mesh, U, gx, gy, times, N):
        self.mesh, self.U, self.gx, self.gy, self.times, self.N = mesh, U, gx, gy, times, N

    def last(self):
        return self.U[:, :, -1]

    def getprop(self, name):
        k = name.lower()
        if k == 'nodalsolution':
            return out(_sq(self.U, self.N))
        if k == 'xgradients':
            return out(_sq(self.gx, self.N))
        if k == 'ygradients':
            return out(_sq(self.gy, self.N))
        if k == 'zgradients':
            return EMPTY()
        if k == 'solutiontimes':
            return out(self.times.reshape(1, -1))
        if k == 'mesh':
            return self.mesh_prop()
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'TimeDependentResults'.")

    def propnames(self):
        return ['NodalSolution', 'SolutionTimes', 'XGradients', 'YGradients', 'ZGradients', 'Mesh']

    def display_lines(self):
        npn, nt = self.U.shape[0], self.U.shape[2]
        sz = f'{npn}×{nt}' if self.N == 1 else f'{npn}×{self.N}×{nt}'
        return ['  TimeDependentResults with properties:', '', f'    NodalSolution: [{sz} double]', f'    SolutionTimes: [1×{nt} double]',
                f'       XGradients: [{sz} double]', f'       YGradients: [{sz} double]', '       ZGradients: []', '             Mesh: [1×1 FEMesh]']


class EigenResults(_Results):
    cls = 'pde.EigenResults'

    def __init__(self, mesh, V, w, N):
        self.mesh, self.V, self.w, self.N = mesh, V, w, N

    def last(self):
        return self.V[:, :, 0] if self.V.shape[2] else np.zeros(self.V.shape[:2])

    def getprop(self, name):
        k = name.lower()
        if k == 'eigenvectors':
            return out(_sq(self.V, self.N))
        if k == 'eigenvalues':
            return out(self.w.reshape(-1, 1))
        if k == 'mesh':
            return self.mesh_prop()
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'EigenResults'.")

    def propnames(self):
        return ['Eigenvectors', 'Eigenvalues', 'Mesh']

    def display_lines(self):
        npn, k = self.V.shape[0], self.V.shape[2]
        sz = f'{npn}×{k}' if self.N == 1 else f'{npn}×{self.N}×{k}'
        return ['  EigenResults with properties:', '', f'    Eigenvectors: [{sz} double]', f'     Eigenvalues: [{k}×1 double]', '            Mesh: [1×1 FEMesh]']


def _locate(mesh, Q):
    """For each query point: its element (-1 outside) and barycentric coordinates in the element's corner triangle."""
    from scipy.spatial import cKDTree
    t = mesh.t[:, :3]
    A, B, C = mesh.p[t[:, 0]], mesh.p[t[:, 1]], mesh.p[t[:, 2]]
    cen = (A + B + C) / 3
    tree = cKDTree(cen)
    k = min(12, t.shape[0])
    _, cand = tree.query(Q, k=k)
    cand = cand.reshape(Q.shape[0], -1)
    el = -np.ones(Q.shape[0], int)
    bary = np.zeros((Q.shape[0], 3))

    def bc(e, q):
        a, b, c = A[e], B[e], C[e]
        den = (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])
        l2 = ((q[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (q[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])) / den
        l3 = ((b[..., 0] - a[..., 0]) * (q[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (q[..., 0] - a[..., 0])) / den
        return np.stack([1 - l2 - l3, l2, l3], axis=-1)
    tol = 1e-9
    for j in range(cand.shape[1]):
        todo = el < 0
        if not todo.any():
            break
        e = cand[todo, j]
        L = bc(e, Q[todo])
        ok = np.all(L >= -tol, axis=1)
        idx = np.flatnonzero(todo)[ok]
        el[idx] = e[ok]
        bary[idx] = L[ok]
    for i in np.flatnonzero(el < 0):
        L = bc(np.arange(t.shape[0]), np.broadcast_to(Q[i], (t.shape[0], 2)))
        ok = np.flatnonzero(np.all(L >= -1e-7, axis=1))
        if ok.size:
            el[i] = ok[0]
            bary[i] = L[ok[0]]
    return el, bary


def _values_at(mesh, U, Q):
    """U (np, ...) at the points Q by the elements' basis functions (NaN outside the mesh); and their gradients."""
    el, L = _locate(mesh, Q)
    shp = U.shape[1:]
    flat = U.reshape(U.shape[0], -1)
    vals = np.full((Q.shape[0], flat.shape[1]), np.nan)
    gxs, gys = vals.copy(), vals.copy()
    ok = el >= 0
    if ok.any():
        e = el[ok]
        xi, eta = L[ok, 1], L[ok, 2]
        N, dN = _shape(mesh.order, xi, eta)
        nodes = mesh.t[e]
        vals[ok] = np.einsum('nb,nbk->nk', N, flat[nodes])
        X = mesh.p[nodes]
        J = np.einsum('nbd,nbx->nxd', dN, X)
        det = J[:, 0, 0] * J[:, 1, 1] - J[:, 0, 1] * J[:, 1, 0]
        inv = np.empty_like(J)
        inv[:, 0, 0], inv[:, 1, 1] = J[:, 1, 1] / det, J[:, 0, 0] / det
        inv[:, 0, 1], inv[:, 1, 0] = -J[:, 0, 1] / det, -J[:, 1, 0] / det
        gr = np.einsum('nbd,ndx->nbx', dN, inv)
        gxs[ok] = np.einsum('nb,nbk->nk', gr[..., 0], flat[nodes])
        gys[ok] = np.einsum('nb,nbk->nk', gr[..., 1], flat[nodes])
    return vals.reshape((Q.shape[0],) + shp), gxs.reshape((Q.shape[0],) + shp), gys.reshape((Q.shape[0],) + shp)


def _query(args, fn):
    """The query points (n, 2) and the remaining arguments."""
    a = np.asarray(darr(args[0]), float)
    if len(args) == 1 or (a.ndim == 2 and a.shape[0] == 2 and len(args) >= 1 and (len(args) == 1 or numel(args[1]) != a.size)):
        if a.ndim == 2 and a.shape[0] == 2:
            return a.T, list(args[1:])
    if len(args) < 2:
        raise err(f'pde:{fn}:points', f'{fn}(results, xq, yq) or {fn}(results, querypoints).', fn)
    x = a.reshape(-1, order='F')
    y = np.asarray(darr(args[1]), float).reshape(-1, order='F')
    if x.size != y.size:
        raise err(f'pde:{fn}:points', 'xq and yq must have as many points.', fn)
    return np.column_stack([x, y]), list(args[2:])


def _pick(res, rest, fn):
    """The component and time (or mode) indices after the points."""
    idx = [np.asarray(darr(v), float).reshape(-1).astype(int) - 1 for v in rest]
    if isinstance(res, StationaryResults):
        iU = idx[0] if (res.N > 1 and idx) else np.array([0]) if res.N == 1 else np.arange(res.N)
        return res.U[:, iU], iU, None
    data = res.U if isinstance(res, TimeDependentResults) else res.V
    if res.N == 1:
        iT = idx[0] if idx else np.arange(data.shape[2])
        return data[:, 0, :][:, iT], None, iT
    if len(idx) < 2:
        raise err(f'pde:{fn}:indices', f'{fn} of a system over time needs the components and the times (iU, iT).', fn)
    return data[:, idx[0]][:, :, idx[1]], idx[0], idx[1]


def _results(v, fn):
    if not isinstance(v, _Results):
        raise err(f'pde:{fn}:results', f'{fn} takes the results of solvepde or solvepdeeig.', fn)
    return v


@bi('interpolateSolution')
def interpolateSolution(nargout, *args):
    """uintrp = interpolateSolution(results, xq, yq), (results, querypoints), (..., iU), (..., iT), (..., iU, iT): the solution at points by the elements' basis functions (NaN outside the mesh): a column for each time or mode; iU the components of a system, iT the times (or modes)."""
    nargchk(args, 2, 5, 'interpolateSolution')
    res = _results(args[0], 'interpolateSolution')
    Q, rest = _query(args[1:], 'interpolateSolution')
    data, iU, iT = _pick(res, rest, 'interpolateSolution')
    v, _, _ = _values_at(res.mesh, data, Q)
    if isinstance(res, StationaryResults) and res.N == 1:
        return out(v.reshape(-1, 1))
    return out(v.reshape(v.shape[0], -1) if v.ndim == 3 and (len(iU) == 1 if iU is not None else True) else v)


@bi('evaluateGradient', nout=3)
def evaluateGradient(nargout, *args):
    """[gradx, grady] = evaluateGradient(results, xq, yq, ...): the solution's gradient at points (the same indices as interpolateSolution)."""
    nargchk(args, 2, 5, 'evaluateGradient')
    res = _results(args[0], 'evaluateGradient')
    Q, rest = _query(args[1:], 'evaluateGradient')
    data, iU, _ = _pick(res, rest, 'evaluateGradient')
    _, gx, gy = _values_at(res.mesh, data, Q)
    if isinstance(res, StationaryResults) and res.N == 1:
        gx, gy = gx.reshape(-1, 1), gy.reshape(-1, 1)
    return _outs(nargout, out(gx), out(gy), np.zeros((0, 0)))


# ---- pdeplot -----------------------------------------------------------------------------------------------------------------------------

def _linear_tris(mesh):
    """The elements as 3-node triangles: a quadratic one as its four corner-and-midside triangles."""
    t = mesh.t
    if mesh.order == 'linear':
        return t
    return np.vstack([t[:, [0, 3, 5]], t[:, [3, 1, 4]], t[:, [5, 4, 2]], t[:, [3, 4, 5]]])


def _isolines(P, T, u, levels):
    xs, ys = [], []
    for lv in levels:
        pts = []
        for (i, j) in ((0, 1), (1, 2), (2, 0)):
            ui, uj = u[T[:, i]], u[T[:, j]]
            with np.errstate(divide='ignore', invalid='ignore'):
                s = (lv - ui) / (uj - ui)
            hit = ((ui - lv) * (uj - lv) < 0) & np.isfinite(s)
            p = P[T[:, i]] + s[:, None] * (P[T[:, j]] - P[T[:, i]])
            pts.append((hit, p))
        for k in range(T.shape[0]):
            got = [p[k] for hit, p in pts if hit[k]]
            if len(got) == 2:
                xs += [got[0][0], got[1][0], np.nan]
                ys += [got[0][1], got[1][1], np.nan]
    return np.array(xs), np.array(ys)


@bi('pdeplot')
def pdeplot(nargout, *args):
    """pdeplot(model), pdeplot(model, 'XYData', u, 'ZData', u, 'ColorMap', cm, 'Contour', 'on', 'Levels', n, 'Mesh', 'on', 'FlowData', [ux uy], 'ColorBar', 'off'), pdeplot(mesh, ...): the mesh, or nodal data on it in colour (interpolated), as a surface (ZData), with contour lines, the mesh and arrows; h = pdeplot(...) the patch."""
    nargchk(args, 1, 21, 'pdeplot')
    first = args[0]
    mesh = PG._femesh(first, 'pdeplot')
    o = PG._opts(list(args[1:]), ('xydata', 'zdata', 'colormap', 'contour', 'levels', 'mesh', 'flowdata', 'colorbar', 'xystyle', 'zstyle',
                                  'flowstyle', 'title', 'facealpha', 'nodelabels', 'elementlabels'), 'pdeplot')
    ax = R._builtin('gca')
    npn = mesh.p.shape[0]
    T = _linear_tris(mesh)
    h = None
    if 'xydata' not in o and 'zdata' not in o and 'flowdata' not in o:
        PG.draw_mesh(mesh, ax, node_labels=PG._onoff(o, 'nodelabels'), elem_labels=PG._onoff(o, 'elementlabels'))
        R._builtin('axis', ax, Char.of('equal'))
        return None
    u = np.asarray(darr(o['xydata']), float).reshape(-1) if 'xydata' in o else None
    z = np.asarray(darr(o['zdata']), float).reshape(-1) if 'zdata' in o else None
    for v, nm in ((u, 'XYData'), (z, 'ZData')):
        if v is not None and v.size != npn:
            raise err('pde:pdeplot:data', f'{nm} has a value for each of the {npn} nodes.', 'pdeplot')
    held = ax.props.get('NextPlot') == 'add'
    if u is not None or z is not None:
        V = np.column_stack([mesh.p, z]) if z is not None else mesh.p
        cdata = u if u is not None else z
        style = py_str(o['xystyle']).lower() if 'xystyle' in o else 'interp'
        h = R._builtin('patch', ax, Char.of('Faces'), out(T + 1.0), Char.of('Vertices'), out(V), Char.of('FaceVertexCData'), out(cdata.reshape(-1, 1)),
                       Char.of('FaceColor'), Char.of('interp' if style != 'flat' else 'flat'), Char.of('EdgeColor'), Char.of('none'))
        R._builtin('hold', ax, Char.of('on'))
        if 'colormap' in o:
            R._builtin('colormap', ax, o['colormap'])
        if not ('colorbar' in o and not PG._onoff(o, 'colorbar')):
            R._builtin('colorbar', ax)
        if z is not None:
            R._builtin('view', ax, 3.0)
    if PG._onoff(o, 'contour') and u is not None:
        lv = o.get('levels')
        if lv is not None and numel(lv) > 1:
            levels = np.asarray(darr(lv), float).reshape(-1)
        else:
            n = int(np.asarray(darr(lv)).reshape(-1)[0]) if lv is not None else 10
            levels = np.linspace(u.min(), u.max(), n + 2)[1:-1]
        xs, ys = _isolines(mesh.p, T, u, levels)
        if xs.size:
            R._builtin('plot', ax, out(xs.reshape(-1, 1)), out(ys.reshape(-1, 1)), Char.of('k'))
        R._builtin('hold', ax, Char.of('on'))
    if PG._onoff(o, 'mesh'):
        PG.draw_mesh(mesh, ax, color=(0.0, 0.0, 0.0))
        R._builtin('hold', ax, Char.of('on'))
    if 'flowdata' in o:
        Fd = np.asarray(darr(o['flowdata']), float)
        Fd = Fd.reshape(npn, 2) if Fd.shape != (npn, 2) and Fd.size == 2 * npn else Fd
        corners = np.unique(mesh.t[:, :3])
        R._builtin('quiver', ax, out(mesh.p[corners, 0].reshape(-1, 1)), out(mesh.p[corners, 1].reshape(-1, 1)),
                   out(Fd[corners, 0].reshape(-1, 1)), out(Fd[corners, 1].reshape(-1, 1)), Char.of('k'))
    if 'title' in o:
        R._builtin('title', ax, o['title'])
    if not held:
        R._builtin('hold', ax, Char.of('off'))
    if z is None:
        R._builtin('axis', ax, Char.of('equal'))
    return h if nargout else None

