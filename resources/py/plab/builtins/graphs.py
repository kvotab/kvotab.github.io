"""Graphs and networks: graph and digraph, their nodes and edges (as
tables), what changes them (addedge, rmedge, addnode, rmnode, flipedge,
reordernodes, subgraph, simplify), what they are asked (numnodes,
numedges, findnode, findedge, degree, indegree, outdegree, neighbors,
successors, predecessors, inedges, outedges, edgecount, adjacency,
incidence, laplacian, ismultigraph, isdag, hascycles), paths and searches
(shortestpath, shortestpathtree, distances, nearest, bfsearch, dfsearch,
allpaths), structure (conncomp, biconncomp, condensation, toposort,
transclosure, transreduction, minspantree, maxflow, centrality,
isisomorphic) and drawing (plot of a graph, highlight, labelnode,
labeledge, layout).

Nodes are numbered from 1 and may have names; edges keep the order they
are sorted in (by their end nodes, the smaller first for a graph), weights
as a variable of the edge table."""
import functools
import heapq
import math
from collections import deque

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, is_str, darr
from ..values import MError, Obj, Char, Cell, Str, EMPTY, numel, py_str, text_list


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError) as e:
                raise err(f'MATLAB:graphfun:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


# ---- the objects -------------------------------------------------------------------------------------------------------------------

# the functions a graph has as methods: G.name(...) calls name(G, ...)
GRAPH_METHODS = set('''addedge addnode adjacency allcycles allpaths bctree bfsearch centrality condensation conncomp cyclebasis
degree dfsearch distances edgecount findedge findnode flipedge hascycles incidence indegree inedges isdag isisomorphic
ismultigraph isomorphism laplacian maxflow minspantree nearest neighbors numedges numnodes outdegree outedges plot
predecessors reordernodes rmedge rmnode shortestpath shortestpathtree simplify subgraph successors toposort
transclosure transreduction'''.split())


class Graph(Obj):
    """A graph (undirected) or digraph: n nodes (names or none, other node variables) and edges s -> t (0-based) with weights or none."""
    is_handle = False

    def __init__(self, directed, n=0, s=None, t=None, w=None, names=None, evars=None, nvars=None):
        self.directed = directed
        self.n = int(n)
        self.s = np.zeros(0, int) if s is None else np.asarray(s, int)
        self.t = np.zeros(0, int) if t is None else np.asarray(t, int)
        self.w = None if w is None else np.asarray(w, float)
        self.names = names                     # list of str, or None
        self.evars = evars or {}               # other edge variables: name -> array (m rows)
        self.nvars = nvars or {}               # other node variables: name -> array (n rows)
        self.normalize()

    @property
    def cls(self):
        return 'digraph' if self.directed else 'graph'

    def value_copy(self):
        return Graph(self.directed, self.n, self.s.copy(), self.t.copy(), None if self.w is None else self.w.copy(),
                     None if self.names is None else list(self.names), {k: _copy(v) for k, v in self.evars.items()},
                     {k: _copy(v) for k, v in self.nvars.items()})

    @property
    def m(self):
        return self.s.size

    def normalize(self):
        """End nodes put in order (the smaller first for a graph) and the edges sorted by them, stably."""
        if not self.directed and self.m:
            sw = self.s > self.t
            self.s, self.t = np.where(sw, self.t, self.s), np.where(sw, self.s, self.t)
        if self.m:
            order = np.lexsort((self.t, self.s))
            self._take_edges(order)

    def _take_edges(self, idx):
        idx = np.asarray(idx, int)
        self.s, self.t = self.s[idx], self.t[idx]
        if self.w is not None:
            self.w = self.w[idx]
        for k, v in list(self.evars.items()):
            self.evars[k] = _rows(v, idx)

    def weights(self):
        return self.w if self.w is not None else np.ones(self.m)

    def node_label(self, i):
        return self.names[i] if self.names is not None else str(i + 1)

    # ---- tables ----
    def edge_table(self):
        from .tables import Table
        if self.names is not None:
            ends = Cell.empty((self.m, 2))
            for k in range(self.m):
                ends.a[k, 0] = Char.of(self.names[self.s[k]])
                ends.a[k, 1] = Char.of(self.names[self.t[k]])
        else:
            ends = np.column_stack([self.s + 1.0, self.t + 1.0]) if self.m else np.zeros((0, 2))
        vars_, names = [ends], ['EndNodes']
        if self.w is not None:
            vars_.append(self.w.reshape(-1, 1))
            names.append('Weight')
        for k, v in self.evars.items():
            vars_.append(v)
            names.append(k)
        return Table(vars_, names, None, self.m)

    def node_table(self):
        from .tables import Table
        vars_, names = [], []
        if self.names is not None:
            vars_.append(Cell.of_list([Char.of(x) for x in self.names], (self.n, 1)))
            names.append('Name')
        for k, v in self.nvars.items():
            vars_.append(v)
            names.append(k)
        return Table(vars_, names, None, self.n)

    def getprop(self, name):
        k = name.lower()
        if k == 'edges':
            return self.edge_table()
        if k == 'nodes':
            return self.node_table()
        if name in GRAPH_METHODS:
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name)              # G.numnodes, G.shortestpath(1, 3)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        from .tables import Table
        k = name.lower()
        if not isinstance(value, Table):
            raise MError('MATLAB:graphfun:table', f'{name} is a table.')
        if k == 'nodes':
            if value.n != self.n:
                raise MError('MATLAB:graphfun:nodes', f'The node table has a row for each of the {self.n} nodes.')
            self.names, self.nvars = None, {}
            for nm, v in zip(value.names, value.vars):
                if nm == 'Name':
                    self.names = [str(x) for x in text_list(v)]
                    if len(set(self.names)) != len(self.names):
                        raise MError('MATLAB:graphfun:uniqueNames', 'Node names are unique.')
                else:
                    self.nvars[nm] = v
            return
        if k == 'edges':
            if value.n != self.m or 'EndNodes' not in value.names:
                raise MError('MATLAB:graphfun:edges', 'The edge table keeps EndNodes and a row for each edge; change edges with addedge and rmedge.')
            self.w, self.evars = None, {}
            for nm, v in zip(value.names, value.vars):
                if nm == 'Weight':
                    self.w = np.asarray(darr(v), float).reshape(-1)
                elif nm != 'EndNodes':
                    self.evars[nm] = v
            return
        raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def propnames(self):
        return ['Edges', 'Nodes']

    def display_lines(self):
        nv = len(self.node_table().names)
        ev = len(self.edge_table().names)
        return [f'  {self.cls} with properties:', '', f'    Edges: [{self.m}×{ev} table]', f'    Nodes: [{self.n}×{nv} table]']

    # ---- node references ----
    def node_ids(self, v, fn, allow_new=False):
        """0-based node indices from numbers or names (new names added when allowed)."""
        if isinstance(v, (Char, Str, Cell)):
            items = text_list(v) if not isinstance(v, Char) or v.a.shape[0] > 1 else [v.str()]
            if self.names is None:
                if self.n and not allow_new:
                    raise err(f'MATLAB:graphfun:{fn}:noNames', 'The nodes have no names: refer to them by number.', fn)
                if self.n == 0:
                    self.names = []
            out_ = []
            for s in items:
                if s in self.names:
                    out_.append(self.names.index(s))
                elif allow_new:
                    self.names.append(s)
                    self.n += 1
                    for k, vv in self.nvars.items():
                        self.nvars[k] = _pad_rows(vv, 1)
                    out_.append(self.n - 1)
                else:
                    raise err(f'MATLAB:graphfun:{fn}:unknownNode', f"'{s}' is not a node of the graph.", fn)
            return np.array(out_, int)
        ids = np.asarray(darr(v), float).reshape(-1)
        if ids.size and (np.any(ids < 1) or np.any(ids != np.round(ids))):
            raise err(f'MATLAB:graphfun:{fn}:badNode', 'Nodes are numbered from 1.', fn)
        ids = ids.astype(int) - 1
        if ids.size and ids.max() >= self.n:
            if allow_new:
                grow = ids.max() + 1 - self.n
                if self.names is not None:
                    raise err(f'MATLAB:graphfun:{fn}:named', 'The nodes have names: add nodes by name.', fn)
                self.n += grow
                for k, vv in self.nvars.items():
                    self.nvars[k] = _pad_rows(vv, grow)
            else:
                raise err(f'MATLAB:graphfun:{fn}:badNode', f'The graph has {self.n} nodes.', fn)
        return ids

    def csr(self, weighted=True):
        """The sparse adjacency matrix (summing parallel edges); undirected graphs symmetric."""
        import scipy.sparse as sps
        w = self.weights() if weighted else np.ones(self.m)
        A = sps.coo_matrix((w, (self.s, self.t)), shape=(self.n, self.n))
        if not self.directed:
            off = self.s != self.t
            A = A + sps.coo_matrix((w[off], (self.t[off], self.s[off])), shape=(self.n, self.n))
        return A.tocsr()

    def adj_lists(self, reverse=False):
        """For each node, its (neighbour, edge index, weight) in edge order (out-edges, or in-edges when reversed)."""
        L = [[] for _ in range(self.n)]
        w = self.weights()
        for e in range(self.m):
            a, b = int(self.s[e]), int(self.t[e])
            if self.directed:
                if reverse:
                    L[b].append((a, e, w[e]))
                else:
                    L[a].append((b, e, w[e]))
            else:
                L[a].append((b, e, w[e]))
                if a != b:
                    L[b].append((a, e, w[e]))
        return L


def _copy(v):
    return v.copy() if hasattr(v, 'copy') else v


def _rows(v, idx):
    from .tables import _take_rows
    return _take_rows(v, list(idx))


def _pad_rows(v, k):
    from .tables import _cat_rows, _missing_like
    return _cat_rows([v, _missing_like(v, k)])


def _g(v, fn, directed=None):
    if not isinstance(v, Graph):
        raise err(f'MATLAB:graphfun:{fn}:graph', f'{fn} takes a graph or digraph.', fn)
    if directed is True and not v.directed:
        raise err(f'MATLAB:graphfun:{fn}:digraph', f'{fn} takes a digraph.', fn)
    if directed is False and v.directed:
        raise err(f'MATLAB:graphfun:{fn}:graph', f'{fn} takes a graph (undirected).', fn)
    return v


def _nodes_out(G, ids):
    """Nodes given back as the graph names them: a column of names, or of numbers."""
    ids = list(ids)
    if G.names is not None:
        return Cell.of_list([Char.of(G.names[i]) for i in ids], (len(ids), 1))
    return np.array(ids, float).reshape(-1, 1) + 1


def _nodes_row(G, ids):
    ids = list(ids)
    if G.names is not None:
        return Cell.of_list([Char.of(G.names[i]) for i in ids], (1, len(ids)))
    return np.array(ids, float).reshape(1, -1) + 1


# ---- construction -----------------------------------------------------------------------------------------------------------------

def _construct(nargout, args, directed):
    from .tables import Table
    fn = 'digraph' if directed else 'graph'
    a = list(args)
    flags = []
    while a and is_str(a[-1]) and py_str(a[-1]).lower() in ('omitselfloops', 'upper', 'lower'):
        flags.append(py_str(a.pop()).lower())
    G = Graph(directed)
    if not a:
        return G
    if isinstance(a[0], Table):
        T = a[0]
        ends = T.vars[T.names.index('EndNodes')] if 'EndNodes' in T.names else None
        if ends is None:
            raise err(f'MATLAB:graphfun:{fn}:edgeTable', 'The edge table needs EndNodes.', fn)
        if len(a) > 1 and isinstance(a[1], Table):
            _node_info(G, a[1], fn)
        if isinstance(ends, Cell):
            items = ends.a
            s = G.node_ids(Cell(items[:, 0:1]), fn, True)
            t = G.node_ids(Cell(items[:, 1:2]), fn, True)
        else:
            e = np.asarray(darr(ends), float)
            s = G.node_ids(e[:, 0], fn, True)
            t = G.node_ids(e[:, 1], fn, True)
        w = None
        evars = {}
        for nm, v in zip(T.names, T.vars):
            if nm == 'Weight':
                w = np.asarray(darr(v), float).reshape(-1)
            elif nm != 'EndNodes':
                evars[nm] = v
        G.s, G.t, G.w, G.evars = s, t, w, evars
        G.normalize()
        return _omit(G, flags)
    if _is_matrix(a[0]) and (len(a) == 1 or (len(a) == 2 and isinstance(a[1], (Cell, Str, Char, Table)))):
        # an adjacency matrix (and node names or a node table): a numeric matrix gives weights, a logical one none
        from ..values import Sparse
        logical = (a[0].m.dtype == np.bool_) if isinstance(a[0], Sparse) else (isinstance(a[0], (np.ndarray, bool)) and np.asarray(a[0]).dtype == bool)
        A = a[0].m.toarray().astype(float) if isinstance(a[0], Sparse) else np.asarray(darr(a[0]), float)
        if A.ndim != 2 or A.shape[0] != A.shape[1]:
            raise err(f'MATLAB:graphfun:{fn}:square', 'The adjacency matrix is square.', fn)
        if not directed:
            if 'upper' in flags:
                A = np.triu(A)
            elif 'lower' in flags:
                A = np.tril(A).T
            else:
                if not np.array_equal(A, A.T, equal_nan=True):
                    raise err('MATLAB:graphfun:graph:symmetricMatrix', "The adjacency matrix of a graph is symmetric (or use 'upper' or 'lower').", fn)
                A = np.triu(A)
        s, t = np.nonzero(A)
        G.n = A.shape[0]
        if len(a) > 1:
            _node_info(G, a[1], fn)
        G.s, G.t = s.astype(int), t.astype(int)
        G.w = None if logical else A[s, t].astype(float)
        G.normalize()
        return _omit(G, flags)
    # s, t (, weights) (, node count or names or node table)
    sv, tv = a[0], a[1]
    rest = a[2:]
    w = None
    if rest and not isinstance(rest[0], (Cell, Str, Char, Table)):
        w = np.asarray(darr(rest.pop(0)), float).reshape(-1)
        if w.size == 0:
            w = None
    if rest and isinstance(rest[0], Table) and 'EndNodes' not in rest[0].names and rest[0].n == max(numel(sv), numel(tv)):
        ET = rest.pop(0)
        for nm, v in zip(ET.names, ET.vars):
            if nm == 'Weight':
                w = np.asarray(darr(v), float).reshape(-1)
            else:
                G.evars[nm] = v
    if rest:
        x = rest.pop(0)
        if isinstance(x, (Table, Cell, Str, Char)):
            _node_info(G, x, fn)
        else:
            G.n = int(num(x))
    s = G.node_ids(sv, fn, True)
    t = G.node_ids(tv, fn, True)
    if s.size == 1 and t.size > 1:
        s = np.repeat(s, t.size)
    if t.size == 1 and s.size > 1:
        t = np.repeat(t, s.size)
    if s.size != t.size:
        raise err(f'MATLAB:graphfun:{fn}:size', 's and t name as many nodes each.', fn)
    if w is not None:
        if w.size == 1 and s.size > 1:
            w = np.repeat(w, s.size)
        if w.size != s.size:
            raise err(f'MATLAB:graphfun:{fn}:weights', 'A weight for each edge.', fn)
    G.s, G.t, G.w = s, t, w
    G.normalize()
    return _omit(G, flags)


def _is_matrix(v):
    from ..values import Sparse
    return isinstance(v, (Sparse, np.ndarray, float, bool, int)) and not isinstance(v, (Cell, Str, Char))


def _node_info(G, x, fn):
    """Node names (text) or a node table (Name and other variables) given to a constructor."""
    from .tables import Table
    if isinstance(x, Table):
        G.n = x.n
        for nm, v in zip(x.names, x.vars):
            if nm == 'Name':
                G.names = [str(y) for y in text_list(v)]
            else:
                G.nvars[nm] = v
    else:
        G.names = [str(y) for y in (text_list(x) if not isinstance(x, Char) or x.a.shape[0] > 1 else [x.str()])]
        if G.n and len(G.names) != G.n:
            raise err(f'MATLAB:graphfun:{fn}:names', f'A name for each of the {G.n} nodes.', fn)
        G.n = len(G.names)
    if G.names is not None and len(set(G.names)) != len(G.names):
        raise err(f'MATLAB:graphfun:{fn}:uniqueNames', 'Node names are unique.', fn)


def _omit(G, flags):
    if 'omitselfloops' in flags and G.m:
        G._take_edges(np.flatnonzero(G.s != G.t))
    return G


@bi('graph')
def graph(nargout, *args):
    """G = graph, graph(A), graph(A, nodenames), graph(s, t), graph(s, t, weights), graph(s, t, weights, numnodes or nodenames), graph(EdgeTable, NodeTable), graph(..., 'omitselfloops'): an undirected graph."""
    return _construct(nargout, args, False)


@bi('digraph')
def digraph(nargout, *args):
    """G = digraph(A), digraph(s, t, weights, ...), digraph(EdgeTable, NodeTable): a directed graph."""
    return _construct(nargout, args, True)


# ---- what a graph is asked ------------------------------------------------------------------------------------------------------------

@bi('numnodes')
def numnodes(nargout, *args):
    """n = numnodes(G): how many nodes."""
    nargchk(args, 1, 1, 'numnodes')
    return float(_g(args[0], 'numnodes').n)


@bi('numedges')
def numedges(nargout, *args):
    """m = numedges(G): how many edges."""
    nargchk(args, 1, 1, 'numedges')
    return float(_g(args[0], 'numedges').m)


@bi('findnode')
def findnode(nargout, *args):
    """ids = findnode(G, names): the numbers of nodes (0 for a name that is none)."""
    nargchk(args, 2, 2, 'findnode')
    G = _g(args[0], 'findnode')
    v = args[1]
    if isinstance(v, (Char, Str, Cell)):
        items = text_list(v) if not isinstance(v, Char) else [v.str()]
        return np.array([[float(G.names.index(s) + 1) if G.names and s in G.names else 0.0] for s in items]).reshape(-1, 1)
    ids = np.asarray(darr(v), float).reshape(-1)
    return np.where((ids >= 1) & (ids <= G.n), ids, 0.0).reshape(-1, 1)


@bi('findedge', nout=2)
def findedge(nargout, *args):
    """idx = findedge(G, s, t), [s, t] = findedge(G, idx): the edges between nodes (0 where there is none), or the end nodes of edges."""
    nargchk(args, 2, 3, 'findedge')
    G = _g(args[0], 'findedge')
    if len(args) == 2:
        idx = np.asarray(darr(args[1]), int).reshape(-1) - 1
        res = (_nodes_out(G, G.s[idx]), _nodes_out(G, G.t[idx]))
        return res if nargout > 1 else res[0]
    s, t = G.node_ids(args[1], 'findedge'), G.node_ids(args[2], 'findedge')
    if s.size == 1 and t.size > 1:
        s = np.repeat(s, t.size)
    if t.size == 1 and s.size > 1:
        t = np.repeat(t, s.size)
    found = []
    for a_, b_ in zip(s, t):
        hit = 0
        for e in range(G.m):
            if (G.s[e] == a_ and G.t[e] == b_) or (not G.directed and G.s[e] == b_ and G.t[e] == a_):
                hit = e + 1
                break
        found.append(float(hit))
    return np.array(found).reshape(-1, 1)


def _deg(G, which):
    d = np.zeros(G.n)
    for e in range(G.m):
        a_, b_ = int(G.s[e]), int(G.t[e])
        if G.directed:
            if which in ('out', 'all'):
                d[a_] += 1
            if which in ('in', 'all'):
                d[b_] += 1
        else:
            d[a_] += 1
            d[b_] += 1
    return d


def _degree_fn(name, which):
    @bi(name)
    def f(nargout, *args):
        nargchk(args, 1, 2, name)
        G = _g(args[0], name, True if which in ('in', 'out') else None)
        d = _deg(G, which)
        if len(args) > 1:
            d = d[G.node_ids(args[1], name)]
        return d.reshape(-1, 1)
    f.__doc__ = {'degree': 'd = degree(G, nodes): how many edges meet each node (a self-loop counts twice).',
                 'indegree': 'd = indegree(G, nodes): how many edges come into each node.',
                 'outdegree': 'd = outdegree(G, nodes): how many edges leave each node.'}[name]
    return f


_degree_fn('degree', 'all')
_degree_fn('indegree', 'in')
_degree_fn('outdegree', 'out')


def _nbr_fn(name):
    @bi(name, nout=2)
    def f(nargout, *args):
        nargchk(args, 2, 2, name)
        G = _g(args[0], name, None if name == 'neighbors' else True)
        i = int(G.node_ids(args[1], name)[0])
        if name == 'successors' or (name == 'neighbors' and not G.directed):
            L = G.adj_lists()[i]
        elif name == 'predecessors':
            L = G.adj_lists(reverse=True)[i]
        else:
            L = G.adj_lists()[i] + G.adj_lists(reverse=True)[i]
        if name == 'neighbors':
            nodes = sorted(set(x[0] for x in L))
            return _nodes_out(G, nodes)
        L = sorted(L, key=lambda x: (x[1]))
        nodes = [x[0] for x in L]
        res = (_nodes_out(G, nodes), np.array([x[1] + 1.0 for x in L]).reshape(-1, 1))
        return res if nargout > 1 else res[0]
    f.__doc__ = {'neighbors': 'N = neighbors(G, node): the nodes joined to a node (sorted).',
                 'successors': '[s, eid] = successors(G, node): the nodes a node points to, and the edges.',
                 'predecessors': '[p, eid] = predecessors(G, node): the nodes that point to a node, and the edges.'}[name]
    return f


_nbr_fn('neighbors')
_nbr_fn('successors')
_nbr_fn('predecessors')


def _edges_fn(name):
    @bi(name, nout=2)
    def f(nargout, *args):
        nargchk(args, 2, 2, name)
        G = _g(args[0], name)
        i = int(G.node_ids(args[1], name)[0])
        if name == 'outedges':
            es = [e for e in range(G.m) if G.s[e] == i or (not G.directed and G.t[e] == i)]
            other = [int(G.t[e]) if G.s[e] == i else int(G.s[e]) for e in es]
        else:
            es = [e for e in range(G.m) if G.t[e] == i or (not G.directed and G.s[e] == i)]
            other = [int(G.s[e]) if G.t[e] == i else int(G.t[e]) for e in es]
        res = (np.array(es, float).reshape(-1, 1) + 1, _nodes_out(G, other))
        return res if nargout > 1 else res[0]
    f.__doc__ = {'outedges': '[eid, nid] = outedges(G, node): the edges leaving a node, and where they go.',
                 'inedges': '[eid, nid] = inedges(G, node): the edges coming into a node, and where from.'}[name]
    return f


_edges_fn('outedges')
_edges_fn('inedges')


@bi('edgecount')
def edgecount(nargout, *args):
    """c = edgecount(G, s, t): how many edges join s to t."""
    nargchk(args, 3, 3, 'edgecount')
    G = _g(args[0], 'edgecount')
    s, t = G.node_ids(args[1], 'edgecount'), G.node_ids(args[2], 'edgecount')
    if s.size == 1 and t.size > 1:
        s = np.repeat(s, t.size)
    if t.size == 1 and s.size > 1:
        t = np.repeat(t, s.size)
    c = [float(np.sum(((G.s == a_) & (G.t == b_)) | ((~np.array(G.directed)) & (G.s == b_) & (G.t == a_)))) for a_, b_ in zip(s, t)]
    return np.array(c).reshape(-1, 1)


def _sparse_out(M):
    from ..sparsemat import make
    import scipy.sparse as sps
    return make(sps.csc_matrix(M))


@bi('adjacency')
def adjacency(nargout, *args):
    """A = adjacency(G), adjacency(G, 'weighted'), adjacency(G, weights): the sparse adjacency matrix (1 for each pair joined, or the weights)."""
    nargchk(args, 1, 2, 'adjacency')
    G = _g(args[0], 'adjacency')
    if len(args) > 1:
        if is_str(args[1]):
            A = G.csr(True)
        else:
            w = np.asarray(darr(args[1]), float).reshape(-1)
            H = G.value_copy()
            H.w = w
            A = H.csr(True)
    else:
        A = G.csr(False)
        A.data[:] = 1.0
    return _sparse_out(A)


@bi('incidence')
def incidence(nargout, *args):
    """I = incidence(G): the sparse incidence matrix: for a digraph -1 at an edge's source and 1 at its target; for a graph -1 and 1 too (the first end -1)."""
    nargchk(args, 1, 1, 'incidence')
    G = _g(args[0], 'incidence')
    I = np.zeros((G.n, G.m))
    for e in range(G.m):
        if G.s[e] != G.t[e]:
            I[G.s[e], e] = -1
            I[G.t[e], e] = 1
    return _sparse_out(I)


def _laplacian(nargout, G, *rest):
    if G.directed:
        raise err('MATLAB:graphfun:laplacian:graph', 'laplacian takes a graph (undirected).', 'laplacian')
    A = G.csr(False).toarray()
    A = (A != 0).astype(float)
    np.fill_diagonal(A, 0)
    L = np.diag(A.sum(axis=1)) - A
    return _sparse_out(L)


@bi('ismultigraph', nout=2)
def ismultigraph(nargout, *args):
    """tf = ismultigraph(G): whether some pair of nodes is joined by more than one edge (or a node to itself)."""
    nargchk(args, 1, 1, 'ismultigraph')
    G = _g(args[0], 'ismultigraph')
    pairs = list(zip(G.s.tolist(), G.t.tolist()))
    tf = len(set(pairs)) != len(pairs)
    return tf


# ---- changing a graph ---------------------------------------------------------------------------------------------------------------

@bi('addedge')
def addedge(nargout, *args):
    """H = addedge(G, s, t), addedge(G, s, t, w), addedge(G, EdgeTable): edges added (nodes too, when they are new)."""
    from .tables import Table, _cat_rows, _missing_like
    nargchk(args, 2, 4, 'addedge')
    G = _g(args[0], 'addedge').value_copy()
    if isinstance(args[1], Table):
        T = args[1]
        H = _construct(1, (T,), G.directed)
        s = G.node_ids(_nodes_out(H, H.s) if H.names else H.s + 1.0, 'addedge', True)
        t = G.node_ids(_nodes_out(H, H.t) if H.names else H.t + 1.0, 'addedge', True)
        w = H.w
    else:
        s, t = G.node_ids(args[1], 'addedge', True), G.node_ids(args[2], 'addedge', True)
        if s.size == 1 and t.size > 1:
            s = np.repeat(s, t.size)
        if t.size == 1 and s.size > 1:
            t = np.repeat(t, s.size)
        w = np.asarray(darr(args[3]), float).reshape(-1) if len(args) > 3 else None
        if w is not None and w.size == 1:
            w = np.repeat(w, s.size)
    k = s.size
    if w is not None and G.w is None:
        if G.m:
            raise err('MATLAB:graphfun:addedge:weights', 'The graph has no weights: add edges without them (or give G weights first).', 'addedge')
        G.w = np.zeros(0)
    if G.w is not None and w is None:
        w = np.ones(k)
    G.s = np.concatenate([G.s, s])
    G.t = np.concatenate([G.t, t])
    if G.w is not None:
        G.w = np.concatenate([G.w, w])
    for nm, v in list(G.evars.items()):
        G.evars[nm] = _cat_rows([v, _missing_like(v, k)])
    G.normalize()
    return G


@bi('rmedge')
def rmedge(nargout, *args):
    """H = rmedge(G, s, t), rmedge(G, idx): edges taken away (all edges between s and t)."""
    nargchk(args, 2, 3, 'rmedge')
    G = _g(args[0], 'rmedge').value_copy()
    if len(args) == 2:
        drop = set(int(x) - 1 for x in np.asarray(darr(args[1])).reshape(-1))
    else:
        s, t = G.node_ids(args[1], 'rmedge'), G.node_ids(args[2], 'rmedge')
        if s.size == 1 and t.size > 1:
            s = np.repeat(s, t.size)
        if t.size == 1 and s.size > 1:
            t = np.repeat(t, s.size)
        drop = set()
        for a_, b_ in zip(s, t):
            for e in range(G.m):
                if (G.s[e] == a_ and G.t[e] == b_) or (not G.directed and G.s[e] == b_ and G.t[e] == a_):
                    drop.add(e)
    G._take_edges([e for e in range(G.m) if e not in drop])
    return G


@bi('addnode')
def addnode(nargout, *args):
    """H = addnode(G, k), addnode(G, names), addnode(G, NodeTable): nodes added, without edges."""
    from .tables import Table, _cat_rows, _missing_like
    nargchk(args, 2, 2, 'addnode')
    G = _g(args[0], 'addnode').value_copy()
    v = args[1]
    if isinstance(v, Table):
        k = v.n
        if 'Name' in v.names:
            names = [str(x) for x in text_list(v.vars[v.names.index('Name')])]
            if G.names is None and G.n:
                raise err('MATLAB:graphfun:addnode:names', 'The nodes have no names.', 'addnode')
            G.names = (G.names or []) + names
        for nm, vv in zip(v.names, v.vars):
            if nm != 'Name':
                G.nvars[nm] = _cat_rows([G.nvars[nm], vv]) if nm in G.nvars else _cat_rows([_missing_like(vv, G.n), vv])
        G.n += k
    elif isinstance(v, (Char, Str, Cell)):
        names = text_list(v) if not isinstance(v, Char) else [v.str()]
        if G.names is None and G.n:
            raise err('MATLAB:graphfun:addnode:names', 'The nodes have no names: add nodes by number.', 'addnode')
        clash = [x for x in names if G.names and x in G.names]
        if clash:
            raise err('MATLAB:graphfun:addnode:exists', f"'{clash[0]}' is a node already.", 'addnode')
        G.names = (G.names or []) + [str(x) for x in names]
        k = len(names)
        G.n += k
    else:
        k = int(num(v))
        if G.names is not None:
            raise err('MATLAB:graphfun:addnode:named', 'The nodes have names: add nodes by name.', 'addnode')
        G.n += k
    for nm, vv in list(G.nvars.items()):
        if vv is not None and _height(vv) < G.n:
            G.nvars[nm] = _cat_rows([vv, _missing_like(vv, G.n - _height(vv))])
    return G


def _height(v):
    from .tables import _height as h
    return h(v)


@bi('rmnode')
def rmnode(nargout, *args):
    """H = rmnode(G, nodes): nodes taken away, with their edges; the others renumbered."""
    nargchk(args, 2, 2, 'rmnode')
    G = _g(args[0], 'rmnode').value_copy()
    drop = set(G.node_ids(args[1], 'rmnode').tolist())
    keep = [i for i in range(G.n) if i not in drop]
    return _induced(G, keep)


def _induced(G, keep):
    pos = {old: new for new, old in enumerate(keep)}
    es = [e for e in range(G.m) if int(G.s[e]) in pos and int(G.t[e]) in pos]
    H = G.value_copy()
    H._take_edges(es)
    H.s = np.array([pos[int(x)] for x in H.s], int)
    H.t = np.array([pos[int(x)] for x in H.t], int)
    H.n = len(keep)
    if H.names is not None:
        H.names = [G.names[i] for i in keep]
    for nm, v in list(H.nvars.items()):
        H.nvars[nm] = _rows(v, keep)
    H.normalize()
    return H


@bi('subgraph')
def subgraph(nargout, *args):
    """H = subgraph(G, nodes): the graph of those nodes and the edges among them, in the order given."""
    nargchk(args, 2, 2, 'subgraph')
    G = _g(args[0], 'subgraph')
    v = args[1]
    if isinstance(v, np.ndarray) and v.dtype == bool:
        keep = list(np.flatnonzero(v.reshape(-1)))
    else:
        keep = list(G.node_ids(v, 'subgraph'))
    return _induced(G, keep)


@bi('reordernodes', nout=2)
def reordernodes(nargout, *args):
    """[H, idx] = reordernodes(G, order): the nodes renumbered in the order given."""
    nargchk(args, 2, 2, 'reordernodes')
    G = _g(args[0], 'reordernodes')
    order = list(G.node_ids(args[1], 'reordernodes'))
    if sorted(order) != list(range(G.n)):
        raise err('MATLAB:graphfun:reordernodes:perm', 'The order names every node once.', 'reordernodes')
    H = _induced(G, order)
    pos = {o: i for i, o in enumerate(order)}
    pairs = [(pos[int(a_)], pos[int(b_)], e) for e, (a_, b_) in enumerate(zip(G.s, G.t))]
    if not G.directed:
        pairs = [(min(p, q), max(p, q), e) for p, q, e in pairs]
    idx = [e for _, _, e in sorted(pairs, key=lambda x: (x[0], x[1]))]
    return (H, np.array(idx, float).reshape(-1, 1) + 1) if nargout > 1 else H


@bi('flipedge')
def flipedge(nargout, *args):
    """H = flipedge(G), flipedge(G, idx), flipedge(G, s, t): edges of a digraph turned round."""
    nargchk(args, 1, 3, 'flipedge')
    G = _g(args[0], 'flipedge', True).value_copy()
    if len(args) == 1:
        idx = range(G.m)
    elif len(args) == 2:
        idx = [int(x) - 1 for x in np.asarray(darr(args[1])).reshape(-1)]
    else:
        s, t = G.node_ids(args[1], 'flipedge'), G.node_ids(args[2], 'flipedge')
        idx = [e for e in range(G.m) for a_, b_ in zip(s, t) if G.s[e] == a_ and G.t[e] == b_]
    for e in idx:
        G.s[e], G.t[e] = G.t[e], G.s[e]
    G.normalize()
    return G


def _simplify(nargout, G, *rest):
    """simplify(G): one edge for each joined pair (weights summed unless 'min', 'max' or 'first'), no self-loops."""
    method = 'sum'
    keep_loops = False
    for r in rest:
        w = py_str(r).lower()
        if w in ('sum', 'min', 'max', 'first', 'mean'):
            method = w
        elif w == 'keepselfloops':
            keep_loops = True
    H = G.value_copy()
    groups = {}
    for e in range(H.m):
        if H.s[e] == H.t[e] and not keep_loops:
            continue
        groups.setdefault((int(H.s[e]), int(H.t[e])), []).append(e)
    firsts = sorted(v[0] for v in groups.values())
    if H.w is not None:
        nw = {}
        for k, es in groups.items():
            vals = H.w[es]
            nw[es[0]] = {'sum': vals.sum(), 'min': vals.min(), 'max': vals.max(), 'first': vals[0], 'mean': vals.mean()}[method]
        H.w = H.w.copy()
        for e, v in nw.items():
            H.w[e] = v
    H._take_edges(firsts)
    return H


# ---- paths and searches ------------------------------------------------------------------------------------------------------------------

def _dijkstra(G, src, weighted=True, method='auto'):
    """Distances and predecessors from src (Dijkstra; breadth-first unweighted; Bellman-Ford for negative weights)."""
    w = G.weights() if weighted else np.ones(G.m)
    n = G.n
    dist = np.full(n, np.inf)
    pred = np.full(n, -1, int)
    pedge = np.full(n, -1, int)
    dist[src] = 0.0
    L = G.adj_lists()
    if method == 'unweighted' or not weighted:
        q = deque([src])
        while q:
            u = q.popleft()
            for v, e, _ in L[u]:
                if dist[v] == np.inf:
                    dist[v] = dist[u] + 1
                    pred[v], pedge[v] = u, e
                    q.append(v)
        return dist, pred, pedge
    if method in ('mixed',) or (method == 'auto' and np.any(w < 0)):
        for _ in range(n):
            changed = False
            for e in range(G.m):
                for a_, b_ in ((G.s[e], G.t[e]),) + ((() if G.directed else ((G.t[e], G.s[e]),))):
                    if dist[a_] + w[e] < dist[b_] - 1e-15:
                        dist[b_] = dist[a_] + w[e]
                        pred[b_], pedge[b_] = a_, e
                        changed = True
            if not changed:
                break
        else:
            raise err('MATLAB:graphfun:shortestpath:negativeCycle', 'The graph has a cycle of negative weight.', 'shortestpath')
        return dist, pred, pedge
    if np.any(w < 0):
        raise err('MATLAB:graphfun:shortestpath:negativeWeights', "Negative weights need the 'mixed' method.", 'shortestpath')
    done = np.zeros(n, bool)
    h = [(0.0, src)]
    while h:
        d, u = heapq.heappop(h)
        if done[u]:
            continue
        done[u] = True
        for v, e, _ in L[u]:
            nd = d + w[e]
            if nd < dist[v] - 1e-15:
                dist[v] = nd
                pred[v], pedge[v] = u, e
                heapq.heappush(h, (nd, v))
    return dist, pred, pedge


def _method_opt(rest):
    for i in range(len(rest) - 1):
        if is_str(rest[i]) and py_str(rest[i]).lower() == 'method':
            return py_str(rest[i + 1]).lower()
    return 'auto'


@bi('shortestpath', nout=3)
def shortestpath(nargout, *args):
    """[P, d, edgepath] = shortestpath(G, s, t, 'Method', m): the nodes of a shortest path from s to t, its length, and its edges ('unweighted', 'positive', 'mixed' or 'auto')."""
    nargchk(args, 3, 5, 'shortestpath')
    G = _g(args[0], 'shortestpath')
    s, t = int(G.node_ids(args[1], 'shortestpath')[0]), int(G.node_ids(args[2], 'shortestpath')[0])
    method = _method_opt(args[3:])
    dist, pred, pedge = _dijkstra(G, s, G.w is not None and method != 'unweighted', method)
    if not np.isfinite(dist[t]):
        P, E = [], []
    else:
        P, E = [t], []
        while P[-1] != s:
            E.append(pedge[P[-1]])
            P.append(pred[P[-1]])
        P.reverse()
        E.reverse()
    res = (_nodes_row(G, P) if P else (Cell.empty((1, 0)) if G.names else np.zeros((1, 0))), float(dist[t]),
           np.array(E, float).reshape(1, -1) + 1 if E else np.zeros((1, 0)))
    return res[:nargout] if nargout > 1 else res[0]


@bi('distances')
def distances(nargout, *args):
    """d = distances(G), distances(G, s), distances(G, s, t, 'Method', m): the lengths of the shortest paths between nodes (Inf where there is none)."""
    nargchk(args, 1, 5, 'distances')
    G = _g(args[0], 'distances')
    a = list(args[1:])
    method = _method_opt(a)
    a = [x for i, x in enumerate(a) if not (is_str(x) and py_str(x).lower() == 'method') and not (i > 0 and is_str(a[i - 1]) and py_str(a[i - 1]).lower() == 'method')]
    srcs = list(G.node_ids(a[0], 'distances')) if a and not (isinstance(a[0], (Char, Str)) and py_str(a[0]) == 'all') else list(range(G.n))
    tgts = list(G.node_ids(a[1], 'distances')) if len(a) > 1 else list(range(G.n))
    D = np.zeros((len(srcs), len(tgts)))
    for i, s in enumerate(srcs):
        dist, _, _ = _dijkstra(G, s, G.w is not None and method != 'unweighted', method)
        D[i] = dist[tgts]
    return D


@bi('nearest', nout=2)
def nearest(nargout, *args):
    """[nodeIDs, dist] = nearest(G, s, d): the nodes within distance d of s, nearest first ('Direction' 'outgoing' unless 'incoming' for a digraph)."""
    nargchk(args, 3, 7, 'nearest')
    G = _g(args[0], 'nearest')
    s = int(G.node_ids(args[1], 'nearest')[0])
    d = float(num(args[2]))
    method = _method_opt(args[3:])
    H = G
    for i in range(3, len(args) - 1):
        if is_str(args[i]) and py_str(args[i]).lower() == 'direction' and py_str(args[i + 1]).lower() == 'incoming' and G.directed:
            H = G.value_copy()
            H.s, H.t = H.t.copy(), H.s.copy()
    dist, _, _ = _dijkstra(H, s, H.w is not None and method != 'unweighted', method)
    idx = [i for i in np.argsort(dist, kind='stable') if i != s and dist[i] <= d]
    res = (_nodes_out(G, idx), dist[idx].reshape(-1, 1))
    return res if nargout > 1 else res[0]


@bi('shortestpathtree', nout=3)
def shortestpathtree(nargout, *args):
    """[TR, D, E] = shortestpathtree(G, s): the tree of shortest paths from s (a digraph pointing away from s), the distances, and which edges are in it."""
    nargchk(args, 2, 8, 'shortestpathtree')
    G = _g(args[0], 'shortestpathtree')
    s = int(G.node_ids(args[1], 'shortestpathtree')[0])
    method = _method_opt(args[2:])
    dist, pred, pedge = _dijkstra(G, s, G.w is not None and method != 'unweighted', method)
    tree = [v for v in range(G.n) if pred[v] >= 0]
    TR = Graph(True, G.n, [pred[v] for v in tree], tree, None if G.w is None else [G.w[pedge[v]] for v in tree],
               None if G.names is None else list(G.names))
    E = np.zeros((1, G.m), bool)
    for v in tree:
        E[0, pedge[v]] = True
    res = (TR, dist.reshape(1, -1), E)
    return res[:nargout] if nargout > 1 else res[0]


def _search(G, s, depth, restart=False):
    n = G.n
    L = G.adj_lists()
    seen = np.zeros(n, bool)
    order = []
    starts = [s] + ([v for v in range(n) if v != s] if restart else [])
    for st in starts:
        if seen[st]:
            continue
        if depth:
            stack = [(st, iter(sorted(L[st], key=lambda x: x[0])))]
            seen[st] = True
            order.append(st)
            while stack:
                u, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    stack.pop()
                    continue
                v = nxt[0]
                if not seen[v]:
                    seen[v] = True
                    order.append(v)
                    stack.append((v, iter(sorted(L[v], key=lambda x: x[0]))))
        else:
            q = deque([st])
            seen[st] = True
            while q:
                u = q.popleft()
                order.append(u)
                for v, _, _ in sorted(L[u], key=lambda x: x[0]):
                    if not seen[v]:
                        seen[v] = True
                        q.append(v)
    return order


def _search_fn(name, depth):
    @bi(name)
    def f(nargout, *args):
        nargchk(args, 2, 6, name)
        G = _g(args[0], name)
        s = int(G.node_ids(args[1], name)[0])
        restart = False
        for i in range(2, len(args) - 1):
            if is_str(args[i]) and py_str(args[i]).lower() == 'restart':
                restart = bool(num(args[i + 1]))
        evs = [py_str(x).lower() for x in args[2:] if is_str(x) and py_str(x).lower() not in ('restart',)]
        if any(e not in ('discovernode',) for e in evs if e not in ('true', 'false')):
            raise err(f'MATLAB:graphfun:{name}:events', f"{name} gives the nodes in the order it finds them ('discovernode') here.", name)
        return _nodes_out(G, _search(G, s, depth, restart))
    f.__doc__ = {'bfsearch': 'v = bfsearch(G, s), bfsearch(G, s, \'Restart\', true): the nodes in breadth-first order from s (neighbours by number).',
                 'dfsearch': 'v = dfsearch(G, s): the nodes in depth-first order from s (neighbours by number).'}[name]
    return f


_search_fn('bfsearch', False)
_search_fn('dfsearch', True)


@bi('allpaths', nout=2)
def allpaths(nargout, *args):
    """[paths, edgepaths] = allpaths(G, s, t, 'MaxNumPaths', n, 'MaxPathLength', L): every path from s to t that visits no node twice."""
    nargchk(args, 3, 9, 'allpaths')
    G = _g(args[0], 'allpaths')
    s, t = int(G.node_ids(args[1], 'allpaths')[0]), int(G.node_ids(args[2], 'allpaths')[0])
    maxn, maxlen = np.inf, np.inf
    for i in range(3, len(args) - 1):
        if is_str(args[i]):
            k = py_str(args[i]).lower()
            if k == 'maxnumpaths':
                maxn = float(num(args[i + 1]))
            elif k == 'maxpathlength':
                maxlen = float(num(args[i + 1]))
    L = G.adj_lists()
    paths, epaths = [], []

    def go(u, path, ep, seen):
        if len(paths) >= maxn:
            return
        if u == t:
            paths.append(list(path))
            epaths.append(list(ep))
            return
        if len(ep) >= maxlen:
            return
        for v, e, _ in sorted(L[u], key=lambda x: (x[0], x[1])):
            if v not in seen:
                seen.add(v)
                path.append(v)
                ep.append(e)
                go(v, path, ep, seen)
                path.pop()
                ep.pop()
                seen.discard(v)
    go(s, [s], [], {s})
    P = Cell.empty((len(paths), 1))
    E = Cell.empty((len(paths), 1))
    for i, (p, e) in enumerate(zip(paths, epaths)):
        P.a[i, 0] = _nodes_row(G, p)
        E.a[i, 0] = np.array(e, float).reshape(1, -1) + 1
    return (P, E) if nargout > 1 else P


# ---- structure ----------------------------------------------------------------------------------------------------------------------------

def _components(G, strong=True):
    """Component number (from 1) of each node: weak (or undirected) by union of edges; strong by Tarjan; numbered by their smallest node."""
    n = G.n
    if not G.directed or not strong:
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a_, b_ in zip(G.s, G.t):
            ra, rb = find(int(a_)), find(int(b_))
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        roots = [find(i) for i in range(n)]
    else:
        L = G.adj_lists()
        index = [None] * n
        low = [0] * n
        on = [False] * n
        stack = []
        comp = [None] * n
        counter = [0]
        ncomp = [0]
        for root in range(n):
            if index[root] is not None:
                continue
            work = [(root, 0)]
            while work:
                v, i = work.pop()
                if i == 0:
                    index[v] = low[v] = counter[0]
                    counter[0] += 1
                    stack.append(v)
                    on[v] = True
                nbrs = L[v]
                if i < len(nbrs):
                    work.append((v, i + 1))
                    w = nbrs[i][0]
                    if index[w] is None:
                        work.append((w, 0))
                    elif on[w]:
                        low[v] = min(low[v], index[w])
                    continue
                for w, _, _ in nbrs:
                    if comp[w] is None and on[w] and index[w] > index[v]:
                        low[v] = min(low[v], low[w])
                if low[v] == index[v]:
                    while True:
                        w = stack.pop()
                        on[w] = False
                        comp[w] = ncomp[0]
                        if w == v:
                            break
                    ncomp[0] += 1
        roots = comp
    first = {}
    for i, r in enumerate(roots):
        first.setdefault(r, i)
    order = sorted(first, key=lambda r: first[r])
    num_of = {r: k + 1 for k, r in enumerate(order)}
    return np.array([num_of[r] for r in roots], float)


@bi('conncomp', nout=2)
def conncomp(nargout, *args):
    """[bins, binsizes] = conncomp(G), conncomp(G, 'Type', 'weak'), conncomp(..., 'OutputForm', 'cell'): the connected components (strongly connected for a digraph unless 'weak'), numbered by their first node."""
    nargchk(args, 1, 5, 'conncomp')
    G = _g(args[0], 'conncomp')
    strong = True
    form = 'vector'
    for i in range(1, len(args) - 1):
        if is_str(args[i]):
            k = py_str(args[i]).lower()
            if k == 'type':
                strong = py_str(args[i + 1]).lower() == 'strong'
            elif k == 'outputform':
                form = py_str(args[i + 1]).lower()
    bins = _components(G, strong)
    k = int(bins.max()) if bins.size else 0
    sizes = np.array([np.sum(bins == c) for c in range(1, k + 1)], float).reshape(1, -1)
    if form == 'cell':
        C = Cell.empty((1, k))
        for c in range(1, k + 1):
            C.a[0, c - 1] = _nodes_row(G, list(np.flatnonzero(bins == c)))
        return (C, sizes) if nargout > 1 else C
    return (bins.reshape(1, -1), sizes) if nargout > 1 else bins.reshape(1, -1)


@bi('biconncomp', nout=2)
def biconncomp(nargout, *args):
    """[bins, iC] = biconncomp(G): the biconnected component of each edge (and the cut vertices)."""
    nargchk(args, 1, 1, 'biconncomp')
    G = _g(args[0], 'biconncomp', False)
    n = G.n
    L = G.adj_lists()
    disc = [-1] * n
    low = [0] * n
    t = [0]
    estack = []
    comps = np.zeros(G.m)
    cut = set()
    ncomp = [0]

    def dfs(u, pe):
        disc[u] = low[u] = t[0]
        t[0] += 1
        children = 0
        for v, e, _ in L[u]:
            if e == pe:
                continue
            if disc[v] == -1:
                estack.append(e)
                children += 1
                dfs(v, e)
                low[u] = min(low[u], low[v])
                if (pe == -1 and children > 1) or (pe != -1 and low[v] >= disc[u]):
                    cut.add(u)
                if low[v] >= disc[u]:
                    ncomp[0] += 1
                    while True:
                        x = estack.pop()
                        comps[x] = ncomp[0]
                        if x == e:
                            break
            elif disc[v] < disc[u]:
                estack.append(e)
                low[u] = min(low[u], disc[v])
    import sys
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 10 * n + 100))
    try:
        for u in range(n):
            if disc[u] == -1:
                dfs(u, -1)
    finally:
        sys.setrecursionlimit(old)
    renum = {}
    for c in comps:
        renum.setdefault(c, len(renum) + 1)
    comps = np.array([renum[c] for c in comps], float)
    res = (comps.reshape(1, -1), np.array(sorted(cut), float).reshape(1, -1) + 1)
    return res if nargout > 1 else res[0]


@bi('condensation')
def condensation(nargout, *args):
    """C = condensation(G): the digraph of the strongly connected components (a node each), acyclic."""
    nargchk(args, 1, 1, 'condensation')
    G = _g(args[0], 'condensation', True)
    bins = _components(G, True).astype(int) - 1
    k = int(bins.max()) + 1 if bins.size else 0
    pairs = sorted(set((bins[a_], bins[b_]) for a_, b_ in zip(G.s, G.t) if bins[a_] != bins[b_]))
    return Graph(True, k, [p[0] for p in pairs], [p[1] for p in pairs])


@bi('toposort', nout=2)
def toposort(nargout, *args):
    """[n, H] = toposort(G), toposort(G, 'Order', 'stable'): the nodes of an acyclic digraph in an order where each edge goes forward (the smallest free node first when 'stable')."""
    nargchk(args, 1, 3, 'toposort')
    G = _g(args[0], 'toposort', True)
    indeg = _deg(G, 'in').astype(int)
    L = G.adj_lists()
    h = [i for i in range(G.n) if indeg[i] == 0]
    heapq.heapify(h)
    order = []
    while h:
        u = heapq.heappop(h)
        order.append(u)
        for v, _, _ in L[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                heapq.heappush(h, v)
    if len(order) != G.n:
        raise err('MATLAB:graphfun:toposort:NotDAG', 'The graph has a cycle: there is no topological order.', 'toposort')
    res = (np.array(order, float).reshape(1, -1) + 1, _induced(G, order))
    return res if nargout > 1 else res[0]


@bi('isdag')
def isdag(nargout, *args):
    """tf = isdag(G): whether a digraph has no cycle."""
    nargchk(args, 1, 1, 'isdag')
    G = _g(args[0], 'isdag', True)
    try:
        toposort(1, G)
        return True
    except MError:
        return False


@bi('hascycles')
def hascycles(nargout, *args):
    """tf = hascycles(G): whether the graph has a cycle (a self-loop counts)."""
    nargchk(args, 1, 1, 'hascycles')
    G = _g(args[0], 'hascycles')
    if G.directed:
        return not isdag(1, G)
    if np.any(G.s == G.t):
        return True
    k = int(_components(G).max()) if G.n else 0
    return bool(G.m > G.n - k)


@bi('transclosure')
def transclosure(nargout, *args):
    """H = transclosure(G): a digraph with an edge from each node to every node it can reach."""
    nargchk(args, 1, 1, 'transclosure')
    G = _g(args[0], 'transclosure', True)
    s, t = [], []
    L = G.adj_lists()
    for u in range(G.n):
        # what u reaches by a path of one edge or more (itself, when it is on a cycle)
        seen, q = set(), deque(v for v, _, _ in L[u])
        while q:
            v = q.popleft()
            if v in seen:
                continue
            seen.add(v)
            q.extend(x for x, _, _ in L[v] if x not in seen)
        for v in sorted(seen):
            s.append(u)
            t.append(v)
    return Graph(True, G.n, s, t, None, None if G.names is None else list(G.names))


@bi('transreduction')
def transreduction(nargout, *args):
    """H = transreduction(G): a digraph with the fewest edges that reaches as G does (for an acyclic G, the edges no longer path makes)."""
    nargchk(args, 1, 1, 'transreduction')
    G = _g(args[0], 'transreduction', True)
    # the strongly connected components: a cycle through each (its nodes in order), and between them
    # the edges of the reduced condensation, each an edge of G
    bins = _components(G, True).astype(int) - 1
    k = int(bins.max()) + 1 if G.n else 0
    pairs = sorted(set((int(bins[a_]), int(bins[b_])) for a_, b_ in zip(G.s, G.t) if bins[a_] != bins[b_]))
    C = Graph(True, k, [p[0] for p in pairs], [p[1] for p in pairs])
    CC = transclosure(1, C)
    reach = set(zip(CC.s.tolist(), CC.t.tolist()))
    s, t = [], []
    for A, B in pairs:
        if any((A, K) in reach and (K, B) in reach for K in range(k) if K not in (A, B)):
            continue
        e = next(e for e in range(G.m) if bins[G.s[e]] == A and bins[G.t[e]] == B)
        s.append(int(G.s[e]))
        t.append(int(G.t[e]))
    for c in range(k):
        members = list(np.flatnonzero(bins == c))
        if len(members) > 1:
            for i, u in enumerate(members):
                s.append(int(u))
                t.append(int(members[(i + 1) % len(members)]))
    return Graph(True, G.n, s, t, None, None if G.names is None else list(G.names))


@bi('minspantree', nout=2)
def minspantree(nargout, *args):
    """[T, pred] = minspantree(G), minspantree(G, 'Root', r, 'Type', 'forest'): a minimum spanning tree (Prim's method from the root, node 1 unless given), and each node's predecessor."""
    nargchk(args, 1, 7, 'minspantree')
    G = _g(args[0], 'minspantree', False)
    root = 0
    forest = False
    for i in range(1, len(args) - 1):
        if is_str(args[i]):
            k = py_str(args[i]).lower()
            if k == 'root':
                root = int(G.node_ids(args[i + 1], 'minspantree')[0])
            elif k == 'type':
                forest = py_str(args[i + 1]).lower() == 'forest'
    w = G.weights()
    L = G.adj_lists()
    pred = np.full(G.n, np.nan)
    intree = np.zeros(G.n, bool)
    edges = []
    starts = [root] + ([v for v in range(G.n) if v != root] if forest else [])
    for st in starts:
        if intree[st]:
            continue
        intree[st] = True
        pred[st] = 0
        h = [(w[e], e, st, v) for v, e, _ in L[st]]
        heapq.heapify(h)
        while h:
            ww, e, u, v = heapq.heappop(h)
            if intree[v]:
                continue
            intree[v] = True
            pred[v] = u + 1
            edges.append(e)
            for x, e2, _ in L[v]:
                if not intree[x]:
                    heapq.heappush(h, (w[e2], e2, v, x))
    H = G.value_copy()
    H._take_edges(sorted(edges))
    res = (H, pred.reshape(1, -1))
    return res if nargout > 1 else res[0]


@bi('maxflow', nout=4)
def maxflow(nargout, *args):
    """[mf, GF, cs, ct] = maxflow(G, s, t): the largest flow from s to t through edges whose weights are their capacities, the flow on each edge, and the two sides of a minimum cut."""
    nargchk(args, 3, 4, 'maxflow')
    G = _g(args[0], 'maxflow')
    s, t = int(G.node_ids(args[1], 'maxflow')[0]), int(G.node_ids(args[2], 'maxflow')[0])
    n = G.n
    cap = {}
    w = G.weights()
    for e in range(G.m):
        a_, b_ = int(G.s[e]), int(G.t[e])
        cap[(a_, b_)] = cap.get((a_, b_), 0.0) + w[e]
        if not G.directed:
            cap[(b_, a_)] = cap.get((b_, a_), 0.0) + w[e]
    flow = {}
    nbr = [set() for _ in range(n)]
    for (a_, b_) in cap:
        nbr[a_].add(b_)
        nbr[b_].add(a_)

    def residual(a_, b_):
        return cap.get((a_, b_), 0.0) - flow.get((a_, b_), 0.0) + flow.get((b_, a_), 0.0) * 0
    total = 0.0
    while True:
        # Edmonds-Karp: the shortest augmenting path in the residual graph
        par = {s: None}
        q = deque([s])
        while q and t not in par:
            u = q.popleft()
            for v in sorted(nbr[u]):
                r = cap.get((u, v), 0.0) - flow.get((u, v), 0.0)
                if v not in par and r > 1e-12:
                    par[v] = u
                    q.append(v)
        if t not in par:
            break
        path = []
        v = t
        while par[v] is not None:
            path.append((par[v], v))
            v = par[v]
        aug = min(cap.get((u, v), 0.0) - flow.get((u, v), 0.0) for u, v in path)
        for u, v in path:
            flow[(u, v)] = flow.get((u, v), 0.0) + aug
            flow[(v, u)] = flow.get((v, u), 0.0) - aug
        total += aug
    if nargout <= 1:
        return float(total)
    reach = set(par)
    fs, ft, fw = [], [], []
    for (u, v), f in sorted(flow.items()):
        if f > 1e-12 and (u, v) in cap:
            fs.append(u)
            ft.append(v)
            fw.append(f)
    GF = Graph(True, n, fs, ft, fw, None if G.names is None else list(G.names))
    cs = sorted(reach)
    ct = [i for i in range(n) if i not in reach]
    res = (float(total), GF, _nodes_out(G, cs), _nodes_out(G, ct))
    return res[:nargout]


@bi('centrality')
def centrality(nargout, *args):
    """C = centrality(G, type, Name, Value): how central each node is: 'degree', 'closeness', 'betweenness', 'pagerank', 'eigenvector' (graph), 'indegree', 'outdegree', 'incloseness', 'outcloseness', 'hubs', 'authorities' (digraph)."""
    nargchk(args, 2, 8, 'centrality')
    G = _g(args[0], 'centrality')
    kind = py_str(args[1]).lower()
    o = {}
    for i in range(2, len(args) - 1, 2):
        o[py_str(args[i]).lower()] = args[i + 1]
    n = G.n
    cost = np.asarray(darr(o['cost']), float).reshape(-1) if 'cost' in o else None
    imp = np.asarray(darr(o['importance']), float).reshape(-1) if 'importance' in o else None
    H = G.value_copy()
    if cost is not None:
        H.w = cost
    elif H.w is not None and kind in ('closeness', 'incloseness', 'outcloseness', 'betweenness'):
        H.w = None
    if kind in ('degree', 'indegree', 'outdegree'):
        which = {'degree': 'all', 'indegree': 'in', 'outdegree': 'out'}[kind]
        if imp is not None:
            d = np.zeros(n)
            for e in range(G.m):
                if which in ('all', 'out') or not G.directed:
                    d[G.s[e]] += imp[e]
                if which in ('all', 'in') or not G.directed:
                    d[G.t[e]] += imp[e]
            return d.reshape(-1, 1)
        return _deg(G, which).reshape(-1, 1)
    if kind in ('closeness', 'incloseness', 'outcloseness'):
        HH = H
        if kind == 'incloseness':
            HH = H.value_copy()
            HH.s, HH.t = HH.t.copy(), HH.s.copy()
        c = np.zeros(n)
        for u in range(n):
            dist, _, _ = _dijkstra(HH, u, HH.w is not None)
            fin = np.isfinite(dist)
            reach = fin.sum() - 1
            tot = dist[fin].sum()
            c[u] = (reach / (n - 1)) ** 2 / tot if reach > 0 and tot > 0 else 0.0
        return c.reshape(-1, 1)
    if kind == 'betweenness':
        # Brandes: the shortest paths through each node, from every source
        CB = np.zeros(n)
        L = H.adj_lists()
        w = H.weights()
        for s in range(n):
            S = []
            P = [[] for _ in range(n)]
            sigma = np.zeros(n)
            sigma[s] = 1
            dist = np.full(n, np.inf)
            dist[s] = 0
            if H.w is None:
                q = deque([s])
                while q:
                    v = q.popleft()
                    S.append(v)
                    for x, e, _ in L[v]:
                        if dist[x] == np.inf:
                            dist[x] = dist[v] + 1
                            q.append(x)
                        if dist[x] == dist[v] + 1:
                            sigma[x] += sigma[v]
                            P[x].append(v)
            else:
                h = [(0.0, s, s)]
                seen = np.zeros(n, bool)
                while h:
                    d, pred_, v = heapq.heappop(h)
                    if seen[v]:
                        continue
                    seen[v] = True
                    S.append(v)
                    for x, e, _ in L[v]:
                        nd = d + w[e]
                        if nd < dist[x] - 1e-12:
                            dist[x] = nd
                            sigma[x] = sigma[v]
                            P[x] = [v]
                            heapq.heappush(h, (nd, v, x))
                        elif abs(nd - dist[x]) <= 1e-12 and not seen[x]:
                            sigma[x] += sigma[v]
                            P[x].append(v)
            delta = np.zeros(n)
            for x in reversed(S):
                for v in P[x]:
                    delta[v] += sigma[v] / sigma[x] * (1 + delta[x])
                if x != s:
                    CB[x] += delta[x]
        if not G.directed:
            CB /= 2
        return CB.reshape(-1, 1)
    if kind in ('pagerank', 'eigenvector', 'hubs', 'authorities'):
        A = np.zeros((n, n))
        ww = imp if imp is not None else np.ones(G.m)
        for e in range(G.m):
            A[G.s[e], G.t[e]] += ww[e]
            if not G.directed and G.s[e] != G.t[e]:
                A[G.t[e], G.s[e]] += ww[e]
        maxit = int(num(o.get('maxiterations', 100.0)))
        tol = float(num(o.get('tolerance', 1e-4)))
        if kind == 'pagerank':
            p = float(num(o.get('followprobability', 0.85)))
            out_w = A.sum(axis=1)
            x = np.full(n, 1.0 / n)
            for _ in range(maxit):
                dangling = x[out_w == 0].sum()
                y = p * (A.T @ np.where(out_w > 0, x / np.where(out_w > 0, out_w, 1), 0)) + p * dangling / n + (1 - p) / n
                if np.abs(y - x).sum() < tol * n:
                    x = y
                    break
                x = y
            return (x / x.sum()).reshape(-1, 1)
        if kind == 'eigenvector':
            if G.directed:
                raise err('MATLAB:graphfun:centrality:eigenvector', "'eigenvector' takes a graph (undirected).", 'centrality')
            vals, vecs = np.linalg.eigh(A)
            v = np.abs(vecs[:, np.argmax(vals)])
            return (v / v.sum()).reshape(-1, 1) if v.sum() > 0 else v.reshape(-1, 1)
        M = A @ A.T if kind == 'hubs' else A.T @ A
        vals, vecs = np.linalg.eigh(M)
        v = np.abs(vecs[:, np.argmax(vals)])
        return (v / v.sum()).reshape(-1, 1) if v.sum() > 0 else v.reshape(-1, 1)
    raise err('MATLAB:graphfun:centrality:type', f"'{kind}' is not a centrality type here.", 'centrality')


@bi('isisomorphic')
def isisomorphic(nargout, *args):
    """tf = isisomorphic(G1, G2): whether the graphs are the same but for the nodes' numbering (a backtracking search refined by degrees)."""
    nargchk(args, 2, 6, 'isisomorphic')
    G1, G2 = _g(args[0], 'isisomorphic'), _g(args[1], 'isisomorphic')
    if G1.directed != G2.directed or G1.n != G2.n or G1.m != G2.m:
        return False
    A = G1.csr(False).toarray()
    B = G2.csr(False).toarray()
    if sorted(A.sum(1)) != sorted(B.sum(1)) or sorted(A.sum(0)) != sorted(B.sum(0)):
        return False
    n = G1.n
    da, db = A.sum(1) + 1000 * A.sum(0), B.sum(1) + 1000 * B.sum(0)
    order = sorted(range(n), key=lambda i: -np.count_nonzero(A[i]))
    m = [-1] * n
    used = [False] * n

    def ok(i, j, depth):
        for k in order[:depth]:
            if A[i, k] != B[j, m[k]] or A[k, i] != B[m[k], j]:
                return False
        return A[i, i] == B[j, j]

    def go(depth):
        if depth == n:
            return True
        i = order[depth]
        for j in range(n):
            if not used[j] and da[i] == db[j] and ok(i, j, depth):
                m[i] = j
                used[j] = True
                if go(depth + 1):
                    return True
                used[j] = False
                m[i] = -1
        return False
    return bool(go(0))


# ---- drawing ------------------------------------------------------------------------------------------------------------------------------

def _layout(G, method, opts):
    n = G.n
    if n == 0:
        return np.zeros(0), np.zeros(0)
    if method == 'auto':
        if G.directed and isdag(1, G):
            method = 'layered'
        elif n <= 2:
            method = 'circle'
        else:
            method = 'force'
    if method == 'circle':
        ang = np.pi / 2 - 2 * np.pi * np.arange(n) / n
        x, y = np.cos(ang), np.sin(ang)
        return np.where(np.abs(x) < 1e-12, 0.0, x), np.where(np.abs(y) < 1e-12, 0.0, y)
    if method == 'layered':
        level = _layers(G, opts)
        L = G.adj_lists()
        x = np.zeros(n)
        for lv in range(level.max() + 1):
            members = [i for i in range(n) if level[i] == lv]
            # within a layer, by the mean place of the nodes above (a barycentre)
            if lv > 0:
                prev = {}
                for i in members:
                    ups = [u for u in range(n) if level[u] < lv and any(v == i for v, _, _ in L[u])]
                    prev[i] = np.mean([x[u] for u in ups]) if ups else 0.0
                members.sort(key=lambda i: (prev[i], i))
            for k, i in enumerate(members):
                x[i] = k - (len(members) - 1) / 2
        y = (level.max() - level).astype(float) + 1
        d = py_str(opts.get('direction', Char.of('down'))).lower()
        if d == 'up':
            y = level.astype(float) + 1
        elif d in ('right', 'left'):
            x, y = (level.astype(float) + 1 if d == 'right' else (level.max() - level).astype(float) + 1), -x
        return x, y
    if method == 'subspace':
        A = (G.csr(False).toarray() != 0).astype(float)
        A = np.maximum(A, A.T)
        Lp = np.diag(A.sum(1)) - A
        vals, vecs = np.linalg.eigh(Lp)
        k = 1 if n > 2 else 0
        return vecs[:, min(k, n - 1)], vecs[:, min(k + 1, n - 1)]
    if method == 'force':
        # Fruchterman and Reingold, from the circle, a fixed number of steps
        x, y = _layout(G, 'circle', opts)
        P = np.column_stack([x, y]) * math.sqrt(n)
        A = (G.csr(False).toarray() != 0)
        A = A | A.T
        np.fill_diagonal(A, False)
        k = 1.0
        temp = math.sqrt(n)
        iters = int(num(opts.get('iterations', 100.0)))
        for it in range(iters):
            D = P[:, None, :] - P[None, :, :]
            dist = np.sqrt((D ** 2).sum(-1)) + 1e-9
            rep = (k * k / dist ** 2)[:, :, None] * D
            att = (A * dist / k)[:, :, None] * D
            disp = rep.sum(1) - att.sum(1)
            ln = np.sqrt((disp ** 2).sum(1)) + 1e-9
            P += disp / ln[:, None] * np.minimum(ln, temp)[:, None]
            temp *= 0.95
        P -= P.mean(0)
        return P[:, 0], P[:, 1]
    raise err('MATLAB:graphfun:plot:layout', "The layout is 'auto', 'force', 'layered', 'circle' or 'subspace'.", 'plot')


def _layers(G, opts):
    """The layer of each node: for a digraph the longest path to it once the edges that close cycles (found
    depth first, from the sources) are set aside; for a graph the steps from the first node of its component."""
    n = G.n
    L = G.adj_lists()
    srcs = list(G.node_ids(opts['sources'], 'plot')) if 'sources' in opts else []
    level = np.zeros(n, int)
    if not G.directed:
        seen = np.zeros(n, bool)
        for st in srcs + list(range(n)):
            if seen[st]:
                continue
            seen[st] = True
            q = deque([st])
            while q:
                u = q.popleft()
                for v, _, _ in sorted(L[u]):
                    if not seen[v]:
                        seen[v] = True
                        level[v] = level[u] + 1
                        q.append(v)
        return level
    indeg = _deg(G, 'in')
    starts = srcs + [i for i in range(n) if indeg[i] == 0] + list(range(n))
    state = np.zeros(n, int)            # 0 not seen, 1 on the path, 2 done
    back = set()
    order = []
    for st in starts:
        if state[st]:
            continue
        stack = [(st, iter(L[st]))]
        state[st] = 1
        while stack:
            u, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[u] = 2
                order.append(u)
                stack.pop()
                continue
            v, e, _ = nxt
            if state[v] == 1:
                back.add(e)
            elif state[v] == 0:
                state[v] = 1
                stack.append((v, iter(L[v])))
    for u in reversed(order):
        for v, e, _ in L[u]:
            if e not in back and v != u:
                level[v] = max(level[v], level[u] + 1)
    return level


class GraphPlot(Obj):
    """A drawn graph. Its properties hold what is drawn: NodeColor one colour, a row for each node, 'flat' (NodeCData
    through the colormap) or 'none'; MarkerSize one or one for each node; EdgeColor and LineWidth likewise for edges.
    It draws itself into its axes as patches (edges and arrowheads), a scatter (nodes) and text (labels)."""
    cls = 'matlab.graphics.chart.primitive.GraphPlot'
    is_handle = True
    BLUE = (0.0, 0.447, 0.741)

    def __init__(self, ax, G, x, y):
        self.ax, self.G = ax, G
        n = G.n
        self.p = {'XData': np.asarray(x, float).reshape(1, -1), 'YData': np.asarray(y, float).reshape(1, -1),
                  'NodeColor': np.array([self.BLUE]), 'MarkerSize': 4.0, 'Marker': Char.of('o'), 'NodeCData': EMPTY(),
                  'EdgeColor': np.array([self.BLUE]), 'LineWidth': 0.5, 'LineStyle': Char.of('-'), 'EdgeAlpha': 0.5, 'EdgeCData': EMPTY(),
                  'ArrowSize': 7.0 if G.directed else 0.0, 'ShowArrows': bool(G.directed),
                  'NodeLabel': Cell.of_list([Char.of(G.node_label(i)) for i in range(n)]) if n <= 100 else Cell.empty((1, 0)),
                  'EdgeLabel': Cell.empty((1, 0)), 'NodeFontSize': 8.0, 'EdgeFontSize': 8.0,
                  'NodeLabelColor': np.array([[0.0, 0.0, 0.0]]), 'EdgeLabelColor': np.array([[0.0, 0.0, 0.0]])}
        self.parts = []

    def key(self, name):
        k = next((key for key in self.p if key.lower() == name.lower()), None)
        if k is None:
            raise err('MATLAB:graphfun:plot:property', f"'{name}' is not a property of a graph plot.", 'plot')
        return k

    def getprop(self, name):
        if name.lower() == 'parent':
            return self.ax
        try:
            return self.p[self.key(name)]
        except MError:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'GraphPlot'.")

    def put(self, name, value):
        """A property checked and kept (drawn by draw)."""
        from ..graphics_base import to_color
        k = self.key(name)
        n, m = self.G.n, self.G.m
        if k in ('NodeColor', 'EdgeColor', 'NodeLabelColor', 'EdgeLabelColor'):
            rows = n if k == 'NodeColor' else m if k == 'EdgeColor' else 1
            if is_str(value):
                c = to_color(value, ('none', 'flat') if k in ('NodeColor', 'EdgeColor') else ())
                value = np.array([c]) if isinstance(c, tuple) else Char.of(c)
            else:
                v = np.asarray(darr(value), float)
                if not (v.size == 3 or (v.ndim == 2 and v.shape == (rows, 3))) or np.any((v < 0) | (v > 1)):
                    raise err('MATLAB:graphfun:plot:color', f'{k} is a colour (an RGB row of values from 0 to 1)'
                              + (f', a row for each of the {rows}, ' if rows > 1 else '') + " or a name.", 'plot')
                value = v.reshape(-1, 3)
        elif k in ('MarkerSize', 'LineWidth', 'ArrowSize', 'NodeFontSize', 'EdgeFontSize', 'EdgeAlpha'):
            v = np.asarray(darr(value), float).reshape(-1)
            many = n if k == 'MarkerSize' else m if k == 'LineWidth' else 1
            if v.size not in (1, many) or np.any(v < 0) or (k == 'EdgeAlpha' and np.any(v > 1)):
                raise err('MATLAB:graphfun:plot:size', f'{k} is a value' + (f' or one for each of the {many}' if many > 1 else '') + '.', 'plot')
            value = float(v[0]) if v.size == 1 else v.reshape(1, -1)
        elif k in ('XData', 'YData'):
            v = np.asarray(darr(value), float).reshape(-1)
            if v.size != n:
                raise err('MATLAB:graphfun:plot:coords', f'{k} has a value for each of the {n} nodes.', 'plot')
            value = v.reshape(1, -1)
        elif k in ('NodeCData', 'EdgeCData'):
            v = np.asarray(darr(value), float).reshape(-1)
            want = n if k == 'NodeCData' else m
            if v.size not in (0, want):
                raise err('MATLAB:graphfun:plot:cdata', f'{k} has a value for each of the {want}.', 'plot')
            value = v.reshape(1, -1) if v.size else EMPTY()
            if v.size:
                self.p['NodeColor' if k == 'NodeCData' else 'EdgeColor'] = Char.of('flat')
        elif k in ('NodeLabel', 'EdgeLabel'):
            value = Cell.of_list([Char.of(s) for s in _labels(value)])
        elif k == 'ShowArrows':
            value = bool(np.all(darr(value))) if not is_str(value) else py_str(value).lower() == 'on'
        elif k == 'Marker':
            from ..graphics_base import MARKERS, MARKER_WORDS
            s = py_str(value).lower()
            mk = MARKER_WORDS.get(s, MARKERS.get(s))
            if mk is None:
                raise err('MATLAB:graphfun:plot:marker', f"'{py_str(value)}' is not a marker.", 'plot')
            value = Char.of(mk)
        elif k == 'LineStyle':
            s = py_str(value)
            if s not in ('-', '--', ':', '-.', 'none'):
                raise err('MATLAB:graphfun:plot:linestyle', "LineStyle is '-', '--', ':', '-.' or 'none'.", 'plot')
            value = Char.of(s)
        self.p[k] = value

    def setprop(self, name, value):
        self.put(name, value)
        self.draw()

    def propnames(self):
        return list(self.p)

    def display_lines(self):
        from ..display import summary
        keys = ('NodeColor', 'MarkerSize', 'Marker', 'EdgeColor', 'LineWidth', 'LineStyle', 'NodeLabel', 'EdgeLabel', 'XData', 'YData')
        return ['  GraphPlot with properties:', ''] + [f'    {k.rjust(10)}: {summary(self.p[k])}' for k in keys]

    # ---- colours and sizes, one for each node or edge ----
    def _cmap_rgb(self, vals):
        cm = np.asarray(darr(self.ax.get_value('Colormap')), float)
        lo, hi = np.nanmin(vals), np.nanmax(vals)
        t = np.zeros(vals.size) if hi <= lo else (vals - lo) / (hi - lo)
        return cm[np.clip((t * len(cm)).astype(int), 0, len(cm) - 1)]

    def rgb_rows(self, which):
        """NodeColor or EdgeColor as a row for each (None for 'none')."""
        k, cd = ('NodeColor', 'NodeCData') if which == 'node' else ('EdgeColor', 'EdgeCData')
        count = self.G.n if which == 'node' else self.G.m
        v = self.p[k]
        if is_str(v):
            s = py_str(v)
            if s == 'none':
                return None
            vals = np.asarray(darr(self.p[cd]), float).reshape(-1)
            return self._cmap_rgb(vals) if vals.size == count else np.tile(np.array(self.BLUE), (count, 1))
        v = np.asarray(v, float).reshape(-1, 3)
        return v.copy() if v.shape[0] == count and count != 1 else np.tile(v[0], (count, 1))

    def each(self, key, count):
        v = self.p[key]
        return np.asarray(v, float).reshape(-1).copy() if np.size(v) == count and count != 1 else np.full(count, float(np.asarray(v).reshape(-1)[0]))

    def draw(self):
        from ..graphics_base import Patch, Text, Series
        ax = self.ax
        for h in self.parts:
            if h.valid:
                h.delete_handle()
        self.parts = []
        G = self.G
        x = np.asarray(self.p['XData'], float).reshape(-1)
        y = np.asarray(self.p['YData'], float).reshape(-1)
        span = max(np.ptp(x) if x.size else 0, np.ptp(y) if y.size else 0, 1.0)
        alpha = float(self.p['EdgeAlpha'])
        widths = self.each('LineWidth', G.m)
        sizes = self.each('MarkerSize', G.n)
        arrows = bool(self.p['ShowArrows']) and G.directed and float(self.p['ArrowSize']) > 0
        flat = is_str(self.p['EdgeColor']) and py_str(self.p['EdgeColor']) == 'flat' and numel(self.p['EdgeCData']) == G.m
        ecol = self.rgb_rows('edge')
        if ecol is not None and G.m and py_str(self.p['LineStyle']) != 'none':
            groups = {}
            for e in range(G.m):
                groups.setdefault((widths[e],) if flat else (widths[e], tuple(ecol[e])), []).append(e)
            for gk, es in groups.items():
                verts, faces = [], []
                for e in es:
                    a_, b_ = int(G.s[e]), int(G.t[e])
                    if a_ == b_:
                        t = np.linspace(0, 2 * np.pi, 21)[:-1]
                        r = 0.04 * span
                        pts = np.column_stack([x[a_] + r * (np.cos(t) - 1), y[a_] + r * np.sin(t)])
                    else:
                        pts = np.array([[x[a_], y[a_]], [x[b_], y[b_]]])
                    k0 = len(verts)
                    verts += pts.tolist()
                    faces.append(list(range(k0 + 1, k0 + len(pts) + 1)))
                width = max(len(f) for f in faces)
                F = np.full((len(faces), width), np.nan)
                for i, f in enumerate(faces):
                    F[i, :len(f)] = f
                P = Patch(ax)
                P.props['Vertices'], P.props['Faces'] = np.array(verts, float), F
                P.props['FaceColor'] = 'none'
                P.props['LineWidth'] = gk[0]
                P.props['LineStyle'] = py_str(self.p['LineStyle'])
                if arrows:
                    # the page draws each head in screen space, back from its target by the target's marker
                    P.serial_extra = functools.partial(_arrow_extra, float(self.p['ArrowSize']), [sizes[int(G.t[e])] / 2 + 0.5 for e in es])
                if flat:
                    P.props['EdgeColor'] = 'flat'
                    P.props['FaceVertexCData'] = np.asarray(self.p['EdgeCData'], float).reshape(-1)[es].reshape(-1, 1)
                else:
                    P.props['EdgeColor'] = gk[1]
                    P.props['EdgeAlpha'] = alpha
                self.parts.append(P)
        ncol = self.rgb_rows('node')
        if G.n and ncol is not None and py_str(self.p['Marker']) != 'none':
            S = Series(ax, 'scatter')
            S.props['XData'], S.props['YData'] = x.reshape(1, -1), y.reshape(1, -1)
            S.props['SizeData'] = (self.each('MarkerSize', G.n) ** 2).reshape(1, -1)
            S.props['Marker'] = py_str(self.p['Marker'])
            S.props['MarkerFaceColor'] = S.props['MarkerEdgeColor'] = 'flat'
            if is_str(self.p['NodeColor']) and numel(self.p['NodeCData']) == G.n:
                S.props['CData'] = np.asarray(self.p['NodeCData'], float).reshape(1, -1)
            else:
                S.extra['rgb'] = ncol
            self.parts.append(S)
        labels = text_list(self.p['NodeLabel']) if numel(self.p['NodeLabel']) else []
        for i, s in enumerate(labels[:G.n]):
            if s:
                T = Text(ax)
                T.props['String'] = s
                T.props['Position'] = np.array([[x[i] + span * 0.015, y[i] + span * 0.015, 0.0]])
                T.props['FontSize'] = float(self.p['NodeFontSize'])
                T.props['Color'] = tuple(np.asarray(self.p['NodeLabelColor'], float).reshape(-1)[:3])
                self.parts.append(T)
        elabels = text_list(self.p['EdgeLabel']) if numel(self.p['EdgeLabel']) else []
        for e, s in enumerate(elabels[:G.m]):
            if s:
                a_, b_ = int(G.s[e]), int(G.t[e])
                T = Text(ax)
                T.props['String'] = s
                T.props['Position'] = np.array([[(x[a_] + x[b_]) / 2, (y[a_] + y[b_]) / 2 + (0.06 * span if a_ == b_ else 0.0), 0.0]])
                T.props['FontSize'] = float(self.p['EdgeFontSize'])
                T.props['HorizontalAlignment'] = 'center'
                T.props['Color'] = tuple(np.asarray(self.p['EdgeLabelColor'], float).reshape(-1)[:3])
                self.parts.append(T)
        if G.n:
            pad = 0.08 * span
            ax.props['XLim'] = np.array([[np.nanmin(x) - pad, np.nanmax(x) + pad]])
            ax.props['YLim'] = np.array([[np.nanmin(y) - pad, np.nanmax(y) + pad]])
            ax.props['XLimMode'] = ax.props['YLimMode'] = 'manual'
        ax.touch()


def _arrow_extra(size, backs):
    return {'arrowSize': size, 'arrowBack': backs}


def _plot_graph(nargout, G, *rest, _ax=None):
    from .graphics import newplot
    a = list(rest)
    spec = None
    if a and is_str(a[0]) and len(a) % 2 == 1:
        spec = py_str(a.pop(0))
    if len(a) % 2:
        raise err('MATLAB:graphfun:plot:pairs', 'Options come as names and values.', 'plot')
    o = {}
    for i in range(0, len(a), 2):
        o[py_str(a[i]).lower()] = a[i + 1]
    method = py_str(o.pop('layout', Char.of('auto'))).lower()
    layout_opts = {k: o.pop(k) for k in ('iterations', 'direction', 'sources') if k in o}
    x, y = _layout(G, method, layout_opts)
    ax = newplot(_ax)
    h = GraphPlot(ax, G, x, y)
    if spec:
        from ..graphics_base import parse_linespec
        ps = parse_linespec(spec)
        if ps:
            col, ls, mk = ps
            if col is not None:
                h.p['NodeColor'] = h.p['EdgeColor'] = np.array([col])
            if ls:
                h.p['LineStyle'] = Char.of(ls)
            if mk:
                h.p['Marker'] = Char.of(mk)
    for k, v in o.items():
        h.put(k, v)
    h.draw()
    return h if nargout else None


def _gp(v, fn):
    if not isinstance(v, GraphPlot):
        raise err(f'MATLAB:graphfun:{fn}:plot', f'{fn} takes a graph plot (from plot(G)).', fn)
    return v


@bi('highlight')
def highlight(nargout, *args):
    """highlight(H, nodes), highlight(H, s, t), highlight(H, 'Edges', idx), highlight(H, G), highlight(..., 'NodeColor', c, 'EdgeColor', c, 'MarkerSize', m, 'LineWidth', w): nodes or edges of a graph plot drawn apart (red, larger, unless asked)."""
    nargchk(args, 2, 12, 'highlight')
    h = _gp(args[0], 'highlight')
    G = h.G
    a = list(args[1:])
    nodes, edges = [], []
    if isinstance(a[0], Graph):
        sub = a.pop(0)
        nodes = [G.names.index(nm) for nm in sub.names] if sub.names and G.names else list(range(sub.n))
        for e in range(sub.m):
            ends = (nodes[sub.s[e]], nodes[sub.t[e]])
            edges += [e2 for e2 in range(G.m) if (G.s[e2], G.t[e2]) == ends or (not G.directed and (G.t[e2], G.s[e2]) == ends)][:1]
    elif is_str(a[0]) and py_str(a[0]).lower() == 'edges':
        a.pop(0)
        edges = [int(v) - 1 for v in np.asarray(darr(a.pop(0))).reshape(-1)]
    elif len(a) % 2 == 0:
        s, t = G.node_ids(a.pop(0), 'highlight'), G.node_ids(a.pop(0), 'highlight')
        if s.size == 1 and t.size > 1:
            s = np.repeat(s, t.size)
        if t.size == 1 and s.size > 1:
            t = np.repeat(t, s.size)
        for a_, b_ in zip(s, t):
            edges += [e for e in range(G.m) if (G.s[e] == a_ and G.t[e] == b_) or (not G.directed and G.s[e] == b_ and G.t[e] == a_)]
    else:
        v = a.pop(0)
        nodes = list(np.flatnonzero(v.reshape(-1))) if isinstance(v, np.ndarray) and v.dtype == bool else list(G.node_ids(v, 'highlight'))
    if len(a) % 2:
        raise err('MATLAB:graphfun:highlight:pairs', 'Options come as names and values.', 'highlight')
    o = {py_str(a[i]).lower(): a[i + 1] for i in range(0, len(a), 2)}
    bad = [k for k in o if k not in ('nodecolor', 'edgecolor', 'markersize', 'linewidth')]
    if bad:
        raise err('MATLAB:graphfun:highlight:option', f"'{bad[0]}' is not an option of highlight (NodeColor, EdgeColor, MarkerSize, LineWidth).", 'highlight')
    from ..graphics_base import to_color

    def colour(v):
        c = to_color(v) if is_str(v) else tuple(np.asarray(darr(v), float).reshape(-1)[:3])
        return np.array(c, float)
    nc = colour(o['nodecolor']) if 'nodecolor' in o else np.array([1.0, 0.0, 0.0])
    ec = colour(o['edgecolor']) if 'edgecolor' in o else np.array([1.0, 0.0, 0.0])
    if nodes and not edges and ('edgecolor' in o or 'linewidth' in o):
        # a list of nodes (a path) with edge options: the edges joining each node to the next too
        for a_, b_ in zip(nodes[:-1], nodes[1:]):
            edges += [e for e in range(G.m) if (G.s[e] == a_ and G.t[e] == b_) or (not G.directed and G.s[e] == b_ and G.t[e] == a_)][:1]
    if edges and not nodes and 'nodecolor' in o:
        nodes = sorted(set(int(G.s[e]) for e in edges) | set(int(G.t[e]) for e in edges))
    if nodes:
        rows = h.rgb_rows('node')
        rows = np.tile(np.array(h.BLUE), (G.n, 1)) if rows is None else rows
        rows[nodes] = nc
        h.p['NodeColor'] = rows
        sizes = h.each('MarkerSize', G.n)
        sizes[nodes] = float(num(o['markersize'])) if 'markersize' in o else np.maximum(sizes[nodes] * 1.5, 6.0)
        h.p['MarkerSize'] = sizes.reshape(1, -1)
    if edges:
        rows = h.rgb_rows('edge')
        rows = np.tile(np.array(h.BLUE), (G.m, 1)) if rows is None else rows
        rows[edges] = ec
        h.p['EdgeColor'] = rows
        widths = h.each('LineWidth', G.m)
        widths[edges] = float(num(o['linewidth'])) if 'linewidth' in o else np.maximum(widths[edges] * 3, 1.5)
        h.p['LineWidth'] = widths.reshape(1, -1)
    h.draw()
    return None


def _labels(v):
    if isinstance(v, Char):
        return [v.str()] if v.a.shape[0] <= 1 else v.row_strs()
    if isinstance(v, (Cell, Str)):
        return [str(x) for x in text_list(v)]
    return [f'{x:g}' for x in np.asarray(darr(v)).reshape(-1)]


@bi('labelnode')
def labelnode(nargout, *args):
    """labelnode(H, nodes, labels): labels of nodes in a graph plot."""
    nargchk(args, 3, 3, 'labelnode')
    h = _gp(args[0], 'labelnode')
    ids = h.G.node_ids(args[1], 'labelnode')
    labs = _labels(args[2])
    cur = text_list(h.p['NodeLabel']) if numel(h.p['NodeLabel']) else [''] * h.G.n
    cur = (cur + [''] * h.G.n)[:h.G.n]
    for k, i in enumerate(ids):
        cur[i] = labs[k] if len(labs) == len(ids) else labs[0]
    h.p['NodeLabel'] = Cell.of_list([Char.of(s) for s in cur])
    h.draw()
    return None


@bi('labeledge')
def labeledge(nargout, *args):
    """labeledge(H, s, t, labels), labeledge(H, idx, labels): labels of edges in a graph plot."""
    nargchk(args, 3, 4, 'labeledge')
    h = _gp(args[0], 'labeledge')
    G = h.G
    if len(args) == 3:
        idx = [int(x) - 1 for x in np.asarray(darr(args[1])).reshape(-1)]
        labsrc = args[2]
    else:
        s, t = G.node_ids(args[1], 'labeledge'), G.node_ids(args[2], 'labeledge')
        idx = [e for a_, b_ in zip(s, t) for e in range(G.m) if (G.s[e] == a_ and G.t[e] == b_) or (not G.directed and G.s[e] == b_ and G.t[e] == a_)]
        labsrc = args[3]
    labs = _labels(labsrc)
    cur = text_list(h.p['EdgeLabel']) if numel(h.p['EdgeLabel']) else [''] * G.m
    cur = (cur + [''] * G.m)[:G.m]
    for k, e in enumerate(idx):
        cur[e] = labs[k] if len(labs) == len(idx) else labs[0]
    h.p['EdgeLabel'] = Cell.of_list([Char.of(s) for s in cur])
    h.draw()
    return None


@bi('layout')
def layout(nargout, *args):
    """layout(H, method, Name, Value): a graph plot's nodes placed again: 'auto', 'force', 'layered', 'circle' or 'subspace'."""
    nargchk(args, 1, 8, 'layout')
    h = _gp(args[0], 'layout')
    method = py_str(args[1]).lower() if len(args) > 1 else 'auto'
    o = {}
    for i in range(2, len(args) - 1, 2):
        o[py_str(args[i]).lower()] = args[i + 1]
    x, y = _layout(h.G, method, o)
    h.p['XData'] = np.asarray(x, float).reshape(1, -1)
    h.p['YData'] = np.asarray(y, float).reshape(1, -1)
    h.draw()
    return None


# ---- the builtins that take graphs too ------------------------------------------------------------------------------------------------------

def _wrap(name, handler, test=lambda a: bool(a) and isinstance(a[0], Graph)):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if test(args):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if test(args):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f


def _plot_test(a):
    from .graphics import split_axes_arg
    if a and isinstance(a[0], Graph):
        return True
    ax, rest = split_axes_arg(list(a))
    return ax is not None and bool(rest) and isinstance(rest[0], Graph)


def _plot_entry(nargout, *a):
    from .graphics import split_axes_arg
    ax, rest = split_axes_arg(list(a))
    return _plot_graph(nargout, rest[0], *rest[1:], _ax=ax)


_wrap('plot', _plot_entry, _plot_test)
_wrap('laplacian', _laplacian)
_wrap('simplify', _simplify)
