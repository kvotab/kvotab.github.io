"""Graphs and networks, run natively (CPython with numpy, scipy and
networkx): graph and digraph made every way, their edge and node tables,
what changes them, degrees and neighbours, and the algorithms checked
against networkx and scipy.sparse.csgraph on random graphs (shortest paths
with and without negative weights, spanning trees, components, biconnected
components and cut vertices, topological order, closure and reduction,
maximum flow, every kind of centrality, isomorphism); then plot of a graph,
highlight, labels and layouts.

    python3 test_graphs.py          (from any folder)
"""
import asyncio
import os
import sys

import networkx as nx
import numpy as np
from scipy.sparse import csgraph, csr_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(code))
    return dict(R.BASE), R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def a(x):
    if isinstance(x, tuple):
        parts = [np.asarray(v, dtype=float).reshape(-1) for v in x]
        return np.concatenate(parts) if parts else np.zeros(0)
    if hasattr(x, 'm') and hasattr(x.m, 'toarray'):
        return x.m.toarray().astype(float)
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 6).tolist() if g.size < 40 else g.shape}, want {np.round(w, 6).tolist() if w.size < 40 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def texts(v):
    from plab.values import py_str
    return [x.str() if isinstance(x, Char) else py_str(x) for x in v.a.reshape(-1, order='F')]


def to_nx(G):
    """The engine's graph as a networkx (multi)graph with the same nodes (0-based) and weights."""
    H = (nx.MultiDiGraph() if G.directed else nx.MultiGraph())
    H.add_nodes_from(range(G.n))
    for k, (s, t) in enumerate(zip(G.s, G.t)):
        H.add_edge(int(s), int(t), weight=float(G.w[k]) if G.w is not None else 1.0, idx=k)
    return H


def simple(H):
    S = nx.DiGraph() if H.is_directed() else nx.Graph()
    S.add_nodes_from(H.nodes)
    S.add_edges_from((u, v) for u, v in H.edges() if u != v)
    return S


rng = np.random.default_rng(7)


def random_edges(n, m, directed, weights=True, lo=1, hi=10):
    pairs = set()
    while len(pairs) < m:
        s, t = rng.integers(1, n + 1, 2)
        if s == t:
            continue
        key = (s, t) if directed else (min(s, t), max(s, t))
        pairs.add(key)
    pairs = sorted(pairs)
    s = [p[0] for p in pairs]
    t = [p[1] for p in pairs]
    w = rng.integers(lo, hi, len(pairs)).astype(float) if weights else None
    return s, t, w


def mat(v):
    return '[' + ' '.join(f'{x:.17g}' for x in v) + ']'


# ---- making graphs ------------------------------------------------------------------------------------------------------------------
W, out = run("G = graph([3 1 2], [1 2 3], [7 8 9])\nE = G.Edges; en = E.EndNodes; ew = E.Weight; "
             "D = digraph([3 1 1], [1 2 3]); den = D.Edges.EndNodes; "
             "A = [0 2 0; 2 0 5; 0 5 0]; GA = graph(A); ga = GA.Edges.EndNodes; gw = GA.Edges.Weight; "
             "GL = graph(logical(A)); gln = GL.Edges.Properties.VariableNames; "
             "GU = graph([0 1 1; 0 0 1; 0 0 0], 'upper'); gu = numedges(GU); "
             "DA = digraph([0 1 0; 0 0 1; 1 0 0]); da = DA.Edges.EndNodes; "
             "N = graph({'x','y'}, {'y','z'}); nn = N.Nodes.Name; nen = N.Edges.EndNodes; "
             "N2 = graph([1 2], [2 3], [], {'a','b','c'}); n2 = N2.Nodes.Name; "
             "N3 = graph([1 2], [2 3], [1 1], 6); n3 = numnodes(N3); "
             "O = graph([1 1 2], [1 2 2], 'omitselfloops'); on = numedges(O); "
             "ET = table([1 2; 2 3], [4; 5], {'p'; 'q'}, 'VariableNames', {'EndNodes', 'Weight', 'Tag'}); NT = table({'u';'v';'w'}, [10;20;30], 'VariableNames', {'Name', 'Pop'}); "
             "T = digraph(ET, NT); tn = T.Edges.Properties.VariableNames; tt = T.Edges.Tag; tp = T.Nodes.Pop; tnm = T.Nodes.Name; "
             "Z = graph; z = [numnodes(Z) numedges(Z)]; S = graph(sparse([0 1; 1 0])); s1 = numedges(S);")
near('graph(s, t, w): edges sorted by end nodes, the smaller first, weights following', (W['en'], W['ew']), ([[1, 2], [1, 3], [2, 3]], [[8], [7], [9]]))
near('digraph keeps directions, sorted by source then target', W['den'], [[1, 2], [1, 3], [3, 1]])
near('graph(A): the upper triangle, nonzeros as weights', (W['ga'], W['gw']), ([[1, 2], [2, 3]], [[2], [5]]))
same('graph of a logical matrix: no weights', texts(W['gln']), ['EndNodes'])
near("'upper' reads only the upper triangle; digraph(A) by rows", (W['gu'], W['da']), (3, [[1, 2], [2, 3], [3, 1]]))
same('nodes named by the edges, in the order they come', texts(W['nn']), ['x', 'y', 'z'])
same('EndNodes of a named graph are names', texts(W['nen']), ['x', 'y', 'y', 'z'])
same('names given after empty weights', texts(W['n2']), ['a', 'b', 'c'])
near('a node count past the last named; omitselfloops', (W['n3'], W['on']), (6, 1))
same('edge and node tables: other variables kept', (texts(W['tn']), texts(W['tt']), texts(W['tnm'])), (['EndNodes', 'Weight', 'Tag'], ['p', 'q'], ['u', 'v', 'w']))
near('node variables kept; an empty graph; a sparse adjacency matrix', (W['tp'], W['z'], W['s1']), ([[10], [20], [30]], [0, 0], 1))
same('display of a graph', 'graph with properties' in out and 'Edges: [3×2 table]' in out, True)
raises("graph([0 1; 0 0])", 'symmetric')
raises("graph({'a','a'}, {'b','c'}, [], {'a','a','b'})", 'unique')
raises("G = graph([1 2], [2 3]); shortestpath(G, 1, 'b')", 'no names')
raises("G = graph({'a'}, {'b'}); neighbors(G, 'q')", "'q' is not a node")
raises("G = graph([1 2], [2 3]); degree(G, 9)", 'has 3 nodes')

# ---- what a graph is asked -------------------------------------------------------------------------------------------------------------
W, _ = run("G = graph([1 1 1 2 3 3], [2 3 3 3 3 4]); d = degree(G); d2 = degree(G, [4 1]); nb = neighbors(G, 3); mg = ismultigraph(G); "
           "ec = edgecount(G, 1, 3); ec2 = edgecount(G, 3, 1); fe = findedge(G, [3 2 4], [1 1 1]); [fs, ft] = findedge(G, [2 6]); "
           "[oe, on] = outedges(G, 3); [ie, in] = inedges(G, 1); "
           "D = digraph([1 1 2 3 4], [2 3 3 1 1]); id = indegree(D); od = outdegree(D); [sc, se] = successors(D, 1); [pr, pe] = predecessors(D, 1); "
           "dn = neighbors(D, 1); [de, dno] = outedges(D, 1); [di, dio] = inedges(D, 1); "
           "N = graph({'a','b'}, {'b','c'}); fn = findnode(N, {'c','zz','a'}); nbn = neighbors(N, 'b'); I = incidence(D); A = adjacency(G); AW = adjacency(digraph([1 2], [2 1], [4 5]), 'weighted'); "
           "AV = adjacency(digraph([1 2], [2 3]), [7 8]);")
near('degree: a self-loop counts twice, parallel edges each', (W['d'], W['d2']), ([[3], [2], [6], [1]], [[1], [3]]))
near('neighbors: sorted, each once (a self-loop makes a node its own); ismultigraph; edgecount either way round', (W['nb'], W['mg'], W['ec'], W['ec2']), ([[1], [2], [3], [4]], 1, 2, 2))
near('findedge: the first edge between each pair, 0 for none; end nodes of edges', (W['fe'], W['fs'], W['ft']), ([[2], [1], [0]], [[1], [3]], [[3], [4]]))
near('outedges and inedges of a graph: every edge at the node', (W['oe'], W['on'], W['ie'], W['in']), ([[2], [3], [4], [5], [6]], [[1], [1], [2], [3], [4]], [[1], [2], [3]], [[2], [3], [3]]))
near('indegree and outdegree', (W['id'], W['od']), ([[2], [1], [2], [0]], [[2], [1], [1], [1]]))
near('successors and predecessors with their edges', (W['sc'], W['se'], W['pr'], W['pe']), ([[2], [3]], [[1], [2]], [[3], [4]], [[4], [5]]))
near("neighbors of a digraph's node: either way; outedges and inedges", (W['dn'], W['de'], W['dno'], W['di'], W['dio']), ([[2], [3], [4]], [[1], [2]], [[2], [3]], [[4], [5]], [[3], [4]]))
near('findnode: 0 for a name that is none', W['fn'], [[3], [0], [1]])
same('neighbors of a named graph are names', texts(W['nbn']), ['a', 'c'])
near('incidence: -1 at the source, 1 at the target', W['I'], [[-1, -1, 0, 1, 1], [1, 0, -1, 0, 0], [0, 1, 1, -1, 0], [0, 0, 0, 0, -1]])
near('adjacency: ones (a self-loop on the diagonal), weighted, or weights given', (W['A'], W['AW'], W['AV']),
     ([[0, 1, 1, 0], [1, 0, 1, 0], [1, 1, 1, 1], [0, 0, 1, 0]], [[0, 4], [5, 0]], [[0, 7, 0], [0, 0, 8], [0, 0, 0]]))

# ---- changing a graph ------------------------------------------------------------------------------------------------------------------
W, _ = run("G = graph([1 2], [2 3], [5 6]); H = addedge(G, [3 1], [4 3], [7 8]); he = H.Edges.EndNodes; hw = H.Edges.Weight; hn = numnodes(H); "
           "R1 = rmedge(H, 1, 3); r1 = R1.Edges.EndNodes; R2 = rmedge(H, [1 4]); r2 = R2.Edges.Weight; "
           "A = addnode(G, 2); an = [numnodes(A) numedges(A)]; RN = rmnode(H, 2); rn = RN.Edges.EndNodes; rw = RN.Edges.Weight; "
           "N = graph({'a','b','c'}, {'b','c','a'}); N2 = addnode(N, {'d'}); n2 = N2.Nodes.Name; N3 = addedge(N, 'd', 'a'); n3 = N3.Edges.EndNodes; N4 = rmnode(N, 'b'); n4 = N4.Nodes.Name; "
           "SG = subgraph(H, [3 4 1]); sg = SG.Edges.EndNodes; sw = SG.Edges.Weight; SL = subgraph(H, logical([1 1 0 0])); sl = numedges(SL); "
           "[RO, idx] = reordernodes(H, [4 3 2 1]); ro = RO.Edges.EndNodes; row = RO.Edges.Weight; "
           "D = digraph([1 2], [2 3]); F = flipedge(D); fe = F.Edges.EndNodes; F1 = flipedge(D, 2); f1 = F1.Edges.EndNodes; "
           "M = graph([1 1 2 2 3], [2 2 2 3 3], [1 2 3 4 5]); S = simplify(M); se = S.Edges.EndNodes; sw2 = S.Edges.Weight; "
           "Smin = simplify(M, 'min'); smin = Smin.Edges.Weight; SK = simplify(M, 'keepselfloops'); sk = numedges(SK); "
           "GN = G; GN.Nodes.Size = [1; 2; 3]; gs = GN.Nodes.Size; GE = G; GE.Edges.Weight = [9; 9]; gew = GE.Edges.Weight; G0 = G.Edges.Weight;")
near('addedge adds a node numbered past the last, the edges sorted again', (W['he'], W['hw'], W['hn']), ([[1, 2], [1, 3], [2, 3], [3, 4]], [[5], [8], [6], [7]], 4))
near('rmedge by end nodes and by index', (W['r1'], W['r2']), ([[1, 2], [2, 3], [3, 4]], [[8], [6]]))
near('addnode by count; rmnode renumbers the rest', (W['an'], W['rn'], W['rw']), ([5, 2], [[1, 2], [2, 3]], [[8], [7]]))
same('addnode by name, addedge with a new name, rmnode by name', (texts(W['n2']), texts(W['n3'])[:3], texts(W['n4'])), (['a', 'b', 'c', 'd'], ['a', 'a', 'a'], ['a', 'c']))
near('subgraph in the order given; by a mask', (W['sg'], W['sw'], W['sl']), ([[1, 2], [1, 3]], [[7], [8]], 1))
near('reordernodes: the edges renumbered and resorted, idx where each was', (W['ro'], W['row'], W['idx']), ([[1, 2], [2, 3], [2, 4], [3, 4]], [[7], [6], [8], [5]], [[4], [3], [2], [1]]))
near('flipedge: all, or one', (W['fe'], W['f1']), ([[2, 1], [3, 2]], [[1, 2], [3, 2]]))
near("simplify: weights summed, self-loops gone; 'min'; 'keepselfloops'", (W['se'], W['sw2'], W['smin'], W['sk']), ([[1, 2], [2, 3]], [[3], [4]], [[1], [4]], 4))
near('Nodes and Edges set as tables; the graph a value (a copy unchanged)', (W['gs'], W['gew'], W['G0']), ([[1], [2], [3]], [[9], [9]], [[5], [6]]))
raises("G = graph([1 2], [2 3]); G.Edges = table([1 2], 'VariableNames', {'EndNodes'})", 'addedge and rmedge')
raises("G = graph({'a'}, {'b'}); addnode(G, {'a'})", "'a' is a node already")

# ---- shortest paths: against scipy.sparse.csgraph ---------------------------------------------------------------------------------------
for directed in (True, False):
    n = 25
    s, t, w = random_edges(n, 70, directed)
    fn = 'digraph' if directed else 'graph'
    W, _ = run(f"G = {fn}({mat(s)}, {mat(t)}, {mat(w)}); D = distances(G); [P, d, ep] = shortestpath(G, 1, {n}); DU = distances(G, 1:3, [5 9], 'Method', 'unweighted'); "
               f"[TR, TD, TE] = shortestpathtree(G, 2); trn = numedges(TR); [nn, nd] = nearest(G, 1, 6);")
    M = csr_matrix((w, (np.array(s) - 1, np.array(t) - 1)), shape=(n, n))
    ref = csgraph.shortest_path(M, method='D', directed=directed)
    near(f'{fn}: distances against csgraph (Dijkstra)', W['D'], ref, 1e-12)
    P = a(W['P']).astype(int).reshape(-1)
    Gm = W['G']
    plen = sum(min(Gm.w[k] for k in range(Gm.m) if (Gm.s[k], Gm.t[k]) == (u - 1, v - 1) or (not directed and (Gm.t[k], Gm.s[k]) == (u - 1, v - 1))) for u, v in zip(P[:-1], P[1:])) if P.size else np.inf
    near(f'{fn}: shortestpath is a path of the shortest length, edgepath its edges', (W['d'], plen, a(W['ep']).size), (ref[0, n - 1], ref[0, n - 1], max(P.size - 1, 0)))
    refu = csgraph.shortest_path(M, method='D', directed=directed, unweighted=True)
    near(f'{fn}: unweighted distances between some nodes', W['DU'], refu[np.ix_([0, 1, 2], [4, 8])])
    near(f'{fn}: shortestpathtree: an edge into each node reached, the distances', (W['trn'], W['TD']), (np.isfinite(ref[1]).sum() - 1, ref[1].reshape(1, -1)))
    within = [i for i in np.argsort(ref[0], kind='stable') if i != 0 and ref[0, i] <= 6]
    near(f'{fn}: nearest within 6, nearest first', (np.sort(a(W['nd']).reshape(-1)), len(a(W['nn']))), (np.sort(ref[0, within]), len(within)))

s, t, w = random_edges(12, 30, True, lo=-2, hi=9)
W0, _ = run(f"G = digraph({mat(s)}, {mat(t)}, {mat(w)}); ok = isdag(G);")
if not W0['ok']:
    # keep it acyclic so that no cycle is negative: edges from smaller to larger
    s, t = [min(p) for p in zip(s, t)], [max(p) for p in zip(s, t)]
# one edge for each pair (the lightest), no zero weights: what csr_matrix can stand for
best = {}
for u, v, ww in zip(s, t, w):
    ww = ww if ww != 0 else 0.5
    best[(u, v)] = min(best.get((u, v), np.inf), ww)
s, t, w = [k[0] for k in best], [k[1] for k in best], np.array(list(best.values()))
W, _ = run(f"G = digraph({mat(s)}, {mat(t)}, {mat(w)}); D = distances(G); D2 = distances(G, 'Method', 'mixed'); [p, d] = shortestpath(G, 1, 12);")
M = csr_matrix((w, (np.array(s) - 1, np.array(t) - 1)), shape=(12, 12))
ref = csgraph.shortest_path(M, method='BF', directed=True)
near("negative weights: Bellman and Ford's method (auto and 'mixed') against csgraph", (W['D'], W['D2'], W['d']), (ref, ref, ref[0, 11]), 1e-12)
raises("shortestpath(digraph([1 2 3], [2 3 1], [1 -5 1]), 1, 3)", 'negative weight')
raises("shortestpath(digraph([1 2], [2 3], [1 -5]), 1, 3, 'Method', 'positive')", "'mixed'")
W, _ = run("[p, d] = shortestpath(graph([1 3], [2 4]), 1, 4); pe = isempty(p);")
near('no path: an empty path, Inf', (W['pe'], W['d']), (1, np.inf))

# ---- searches -------------------------------------------------------------------------------------------------------------------------
W, _ = run("G = graph([1 1 2 2 3 4 6], [2 3 4 5 6 7 8]); b = bfsearch(G, 1); d = dfsearch(G, 1); br = bfsearch(graph([1 3], [2 4]), 3, 'Restart', true); "
           "D = digraph([1 1 2 3 2], [2 3 4 4 3]); P = allpaths(D, 1, 4); [P2, E2] = allpaths(D, 1, 4, 'MaxPathLength', 2); np2 = numel(P2); P3 = allpaths(D, 1, 4, 'MaxNumPaths', 1); np3 = numel(P3);")
near('bfsearch and dfsearch, neighbours by number', (W['b'], W['d']), ([[1], [2], [3], [4], [5], [6], [7], [8]], [[1], [2], [4], [7], [5], [3], [6], [8]]))
near("bfsearch with 'Restart'", W['br'], [[3], [4], [1], [2]])
paths = [a(x).astype(int).reshape(-1).tolist() for x in W['P'].a.reshape(-1)]
ref = sorted([[v + 1 for v in p] for p in nx.all_simple_paths(nx.DiGraph([(0, 1), (0, 2), (1, 3), (2, 3), (1, 2)]), 0, 3)])
same('allpaths: every simple path (networkx all_simple_paths)', sorted(paths), ref)
near("allpaths 'MaxPathLength' 2, 'MaxNumPaths' 1", (W['np2'], W['np3']), (2, 1))

# ---- components, cut vertices, order -------------------------------------------------------------------------------------------------------
for trial in range(3):
    n = 30
    s, t, _ = random_edges(n, 34, True, weights=False)
    W, _ = run(f"D = digraph({mat(s)}, {mat(t)}, [], {n}); [bs, ss] = conncomp(D); bw = conncomp(D, 'Type', 'weak'); C = condensation(D); cn = [numnodes(C) numedges(C)]; "
               f"G = graph({mat(s)}, {mat(t)}, [], {n}); bg = conncomp(G); cc = conncomp(G, 'OutputForm', 'cell'); [bb, iC] = biconncomp(G); hc = hascycles(G); hd = hascycles(D); dag = isdag(D);")
    H = to_nx(W['D'])
    strong = list(nx.strongly_connected_components(H))
    weak = list(nx.weakly_connected_components(H))
    bs = a(W['bs']).astype(int).reshape(-1)
    part = lambda bins: sorted(sorted(np.flatnonzero(bins == k).tolist()) for k in np.unique(bins))
    same(f'strong components (networkx), trial {trial}', part(bs), sorted(sorted(c) for c in strong))
    same(f'weak components, trial {trial}', part(a(W['bw']).astype(int).reshape(-1)), sorted(sorted(c) for c in weak))
    firsts = [np.flatnonzero(bs == k)[0] for k in range(1, bs.max() + 1)]
    same(f'components numbered in the order of their first nodes, trial {trial}', firsts, sorted(firsts))
    CN = nx.condensation(simple(H))
    near(f'condensation: nodes and edges (networkx), trial {trial}', W['cn'], [[CN.number_of_nodes(), CN.number_of_edges()]])
    UG = simple(to_nx(W['G']))
    same(f'conncomp of the graph, also as a cell, trial {trial}', (part(a(W['bg']).astype(int).reshape(-1)), sorted(sorted(int(v) - 1 for v in a(x).reshape(-1)) for x in W['cc'].a.reshape(-1))),
         (sorted(sorted(c) for c in nx.connected_components(UG)),) * 2)
    bb = a(W['bb']).astype(int).reshape(-1)
    Gm = W['G']
    mine = sorted(sorted(set((int(Gm.s[e]), int(Gm.t[e])) for e in np.flatnonzero(bb == k))) for k in np.unique(bb))   # parallel edges as one
    theirs = sorted(sorted(tuple(sorted(e)) for e in comp) for comp in nx.biconnected_component_edges(UG))
    same(f'biconncomp: the edges of each biconnected component (networkx), trial {trial}', mine, theirs)
    same(f'biconncomp: the cut vertices, trial {trial}', sorted(a(W['iC']).astype(int).reshape(-1).tolist()), sorted(v + 1 for v in nx.articulation_points(UG)))
    same(f'hascycles, isdag, trial {trial}', (bool(W['hc']), bool(W['hd']), bool(W['dag'])),
         (len(nx.cycle_basis(UG)) > 0, not nx.is_directed_acyclic_graph(simple(H)), nx.is_directed_acyclic_graph(simple(H))))

W, _ = run("D = digraph([1 1 2 5 5 3], [2 3 4 3 4 4]); o = toposort(D); [o2, H] = toposort(D); he = H.Edges.EndNodes;")
near('toposort: the smallest free node next; H renumbered so that every edge goes forward', (W['o'], np.all(a(W['he'])[:, 0] < a(W['he'])[:, 1])), ([1, 2, 5, 3, 4], 1))
raises("toposort(digraph([1 2], [2 1]))", 'cycle')
raises("toposort(graph([1 2], [2 3]))", 'takes a digraph')

for trial in range(2):
    s, t, _ = random_edges(10, 18, True, weights=False)
    W, _ = run(f"D = digraph({mat(s)}, {mat(t)}, [], 10); TC = transclosure(D); TR = transreduction(D); TRC = transclosure(TR); same = isequal(TC.Edges.EndNodes, TRC.Edges.EndNodes); m = [numedges(TR) numedges(D)];")
    H = simple(to_nx(W['D']))
    ref = nx.transitive_closure(H, reflexive=False)
    mine = sorted((int(u), int(v)) for u, v in zip(W['TC'].s, W['TC'].t))
    same(f'transclosure (networkx, a node on a cycle reaching itself), trial {trial}', mine, sorted(ref.edges()))
    near(f'transreduction reaches as the graph does, with no more edges, trial {trial}', (W['same'], a(W['m']).reshape(-1)[0] <= a(W['m']).reshape(-1)[1]), (1, 1))
s, t, _ = random_edges(12, 30, True, weights=False)
s, t = [min(p) for p in zip(s, t)], [max(p) for p in zip(s, t)]
W, _ = run(f"D = digraph({mat(s)}, {mat(t)}, [], 12); TR = transreduction(D);")
same('transreduction of an acyclic digraph: networkx transitive_reduction', sorted((int(u), int(v)) for u, v in zip(W['TR'].s, W['TR'].t)),
     sorted(nx.transitive_reduction(simple(to_nx(W['D']))).edges()))

# ---- spanning trees and flows --------------------------------------------------------------------------------------------------------------
for trial in range(3):
    s, t, w = random_edges(20, 45, False)
    W, _ = run(f"G = graph({mat(s)}, {mat(t)}, {mat(w)}, 22); [T, pred] = minspantree(G); tw = sum(T.Edges.Weight); [TF, pf] = minspantree(G, 'Type', 'forest'); fw = sum(TF.Edges.Weight); "
               f"[T3, p3] = minspantree(G, 'Root', 3);")
    M = csr_matrix((w, (np.array(s) - 1, np.array(t) - 1)), shape=(22, 22))
    ref = csgraph.minimum_spanning_tree(M).sum()
    near(f'minspantree forest: the least total weight (csgraph), trial {trial}', W['fw'], ref, 1e-12)
    comp1 = nx.node_connected_component(simple(to_nx(W['G'])), 0)
    sub = to_nx(W['G']).subgraph(comp1)
    near(f'minspantree from the root: the tree of its component; pred 0 at the root, NaN off it, trial {trial}',
         (W['tw'], a(W['pred'])[0, 0], np.isnan(a(W['pred'])[0, 21]), a(W['p3'])[0, 2]), (nx.minimum_spanning_tree(nx.Graph(sub)).size(weight='weight'), 0, 1, 0), 1e-12)
for directed in (True, False):
    s, t, w = random_edges(15, 40, directed)
    fn = 'digraph' if directed else 'graph'
    W, _ = run(f"G = {fn}({mat(s)}, {mat(t)}, {mat(w)}); [mf, GF, cs, ct] = maxflow(G, 1, 15); gfw = GF.Edges.Weight; gfe = GF.Edges.EndNodes;")
    H = nx.DiGraph()
    for u, v, ww in zip(s, t, w):
        for x, y in ((u, v),) + (() if directed else ((v, u),)):
            H.add_edge(x - 1, y - 1, capacity=H.get_edge_data(x - 1, y - 1, {'capacity': 0})['capacity'] + ww)
    ref = nx.maximum_flow_value(H, 0, 14)
    cs = set(a(W['cs']).astype(int).reshape(-1) - 1)
    cut = sum(d['capacity'] for u, v, d in H.edges(data=True) if u in cs and v not in cs)
    inflow = sum(f for (u, v), f in zip(a(W['gfe']).astype(int) - 1, a(W['gfw']).reshape(-1)) if v == 14)
    near(f'{fn}: maxflow (networkx), the cut it gives as large, the flow into t', (W['mf'], cut, inflow), (ref, ref, ref), 1e-9)
    same(f'{fn}: the cut separates s from t', (0 in cs, 14 in cs), (True, False))

# ---- centrality -------------------------------------------------------------------------------------------------------------------------
n = 18
s, t, w = random_edges(n, 40, False)
W, _ = run(f"G = graph({mat(s)}, {mat(t)}, {mat(w)}); b = centrality(G, 'betweenness'); bc = centrality(G, 'betweenness', 'Cost', G.Edges.Weight); "
           f"c = centrality(G, 'closeness'); cc = centrality(G, 'closeness', 'Cost', G.Edges.Weight); pr = centrality(G, 'pagerank', 'Tolerance', 1e-12, 'MaxIterations', 2000); "
           f"ev = centrality(G, 'eigenvector'); dg = centrality(G, 'degree'); dw = centrality(G, 'degree', 'Importance', G.Edges.Weight);")
H = nx.Graph()
H.add_nodes_from(range(n))
for u, v, ww in zip(s, t, w):
    H.add_edge(u - 1, v - 1, weight=ww)


def col(dct):
    return np.array([dct[i] for i in range(n)]).reshape(-1, 1)


near('betweenness (networkx, not normalized)', W['b'], col(nx.betweenness_centrality(H, normalized=False)), 1e-9)
near("betweenness with 'Cost'", W['bc'], col(nx.betweenness_centrality(H, normalized=False, weight='weight')), 1e-9)
cl = col(nx.closeness_centrality(H, wf_improved=True)) / (n - 1)
near('closeness: (r/(n-1))^2/D, networkx\'s improved form over n - 1', W['c'], cl, 1e-12)
near("closeness with 'Cost'", W['cc'], col(nx.closeness_centrality(H, distance='weight', wf_improved=True)) / (n - 1), 1e-12)
near('pagerank (networkx, unweighted)', W['pr'], col(nx.pagerank(nx.Graph(H.edges()), alpha=0.85, tol=1e-14, max_iter=5000)) if nx.is_connected(H) else W['pr'], 1e-8)
ev = col(nx.eigenvector_centrality_numpy(nx.Graph(H.edges())))
near('eigenvector, summing to 1', W['ev'], np.abs(ev) / np.abs(ev).sum(), 1e-8)
near("degree, and with 'Importance'", (W['dg'], W['dw']), (col(dict(H.degree())), col(dict(H.degree(weight='weight')))))
s, t, _ = random_edges(14, 35, True, weights=False)
W, _ = run(f"D = digraph({mat(s)}, {mat(t)}, [], 14); pr = centrality(D, 'pagerank', 'Tolerance', 1e-12, 'MaxIterations', 2000); h = centrality(D, 'hubs'); au = centrality(D, 'authorities'); "
           f"oc = centrality(D, 'outcloseness'); ic = centrality(D, 'incloseness'); ind = centrality(D, 'indegree'); b = centrality(D, 'betweenness');")
HD = simple(to_nx(W['D']))
n = 14
near('digraph pagerank (dangling nodes spread evenly; networkx)', W['pr'], col(nx.pagerank(HD, alpha=0.85, tol=1e-14, max_iter=5000)), 1e-8)
hubs, auths = nx.hits(HD, max_iter=10000, tol=1e-14)
near('hubs and authorities (networkx hits)', (W['h'], W['au']), (col(hubs), col(auths)), 1e-6)
near("'outcloseness' and 'incloseness'", (W['oc'], W['ic']),
     (col(nx.closeness_centrality(HD.reverse(), wf_improved=True)) / (n - 1), col(nx.closeness_centrality(HD, wf_improved=True)) / (n - 1)), 1e-12)
near('digraph betweenness and indegree', (W['b'], W['ind']), (col(nx.betweenness_centrality(HD, normalized=False)), col(dict(HD.in_degree()))), 1e-9)
raises("centrality(digraph([1 2], [2 3]), 'eigenvector')", 'takes a graph')
raises("centrality(graph([1 2], [2 3]), 'fame')", "'fame'")

# ---- isomorphism ------------------------------------------------------------------------------------------------------------------------
s, t, _ = random_edges(9, 16, False, weights=False)
perm = rng.permutation(9) + 1
W, _ = run(f"G = graph({mat(s)}, {mat(t)}, [], 9); p = {mat(perm)}; H = graph(p({mat(s)}), p({mat(t)}), [], 9); i1 = isisomorphic(G, H); "
           "C6 = graph([1 2 3 4 5 6], [2 3 4 5 6 1]); T3 = graph([1 2 3 4 5 6], [2 3 1 5 6 4]); i2 = isisomorphic(C6, T3); "
           "D1 = digraph([1 2], [2 3]); D2 = digraph([3 2], [2 1]); D3 = digraph([1 1], [2 3]); i3 = [isisomorphic(D1, D2) isisomorphic(D1, D3)];")
near('isisomorphic: a renumbered graph; two triangles are not a hexagon (same degrees); digraphs', (W['i1'], W['i2'], W['i3']), (1, 0, [1, 0]))

# ---- laplacian and simplify still serve symbolic math ----------------------------------------------------------------------------------------
W, _ = run("L = laplacian(graph([1 1 2 2], [2 2 3 3], [5 6 7 8])); syms x y; f = laplacian(x^2 + y^3, [x y]); s = simplify(sin(x)^2 + cos(x)^2); fs = char(f); ss = char(s);")
near('laplacian of a graph: degrees less adjacency, weights and parallel edges not counted', W['L'], [[1, -1, 0], [-1, 2, -1], [0, -1, 1]])
same('laplacian and simplify of symbolic expressions as before', (W['fs'].str(), W['ss'].str()), ('6*y + 2', '1'))

# ---- plotting -----------------------------------------------------------------------------------------------------------------------------
W, out = run("G = graph([1 1 2 3], [2 3 3 4]); h = plot(G); cls = class(h); k = get(gca, 'Children'); types = arrayfun(@(c) string(c.Type), k); "
             "xd = h.XData; nl = h.NodeLabel; "
             "h2 = plot(G, 'Layout', 'circle', 'NodeColor', 'k', 'MarkerSize', 7, 'EdgeLabel', {'a','b','c','d'}); x2 = h2.XData; y2 = h2.YData; nc = h2.NodeColor; ms = h2.MarkerSize; "
             "nt = numel(findobj(gca, 'Type', 'text')); "
             "D = digraph([1 1 2 3], [2 3 4 4]); h3 = plot(D); x3 = h3.XData; y3 = h3.YData; np3 = numel(findobj(gca, 'Type', 'patch')); "
             "h4 = plot(D, 'Layout', 'layered', 'Direction', 'right'); x4 = h4.XData; "
             "h5 = plot(D, 'ShowArrows', false); np5 = numel(findobj(gca, 'Type', 'patch')); "
             "ax = axes; h6 = plot(ax, G, '-or'); c6 = h6.EdgeColor; ")
same('plot(G) gives a GraphPlot', W['cls'].str(), 'matlab.graphics.chart.primitive.GraphPlot')
same('drawn as patches (edges), a scatter (nodes) and text (labels)', sorted(set(texts(W['types']))), ['patch', 'scatter', 'text'])
same('node labels: the numbers', texts(W['nl']), ['1', '2', '3', '4'])
near("'circle' from the top, clockwise; properties set by name", (W['x2'], W['y2'], W['nc'], W['ms']), ([0, 1, 0, -1], [1, 0, -1, 0], [0, 0, 0], 7), 1e-12)
near('node and edge labels drawn as text', W['nt'], 8)
near("a digraph without cycles: 'layered' by default, sources on top; its edges one patch", (W['y3'], W['np3']), ([[3, 2, 2, 1]], 1))
ext3 = W['h3'].parts[0].serial_extra()
same('the edge patch asks the page for arrowheads (ArrowSize), each back from its target by the marker', (ext3['arrowSize'], ext3['arrowBack']), (7.0, [2.5] * 4))
same("'ShowArrows' off: none asked", getattr(W['h5'].parts[0], 'serial_extra', None), None)
near("'Direction', 'right': layers along x", (W['x4'], W['np5']), ([[1, 2, 2, 3]], 1))
near('plot(ax, G, LineSpec)', W['c6'], [[1, 0, 0]])
W, _ = run("G = graph([1 2 3 4], [2 3 4 5]); h = plot(G); highlight(h, [2 4]); s = findobj(gca, 'Type', 'scatter'); sz = s.SizeData; "
           "nc = h.NodeColor; ms = h.MarkerSize; highlight(h, 1, 2, 'EdgeColor', 'g', 'LineWidth', 4); L = findobj(gca, 'Type', 'patch'); lw = sort(arrayfun(@(l) l.LineWidth, L))'; hw = h.LineWidth; ec = h.EdgeColor; "
           "[~, ~, ep] = shortestpath(G, 1, 5); highlight(h, 'Edges', ep, 'EdgeColor', 'm'); "
           "T = minspantree(G); highlight(h, T, 'NodeColor', 'b'); "
           "labelnode(h, [1 5], {'start', 'end'}); nl = h.NodeLabel; labeledge(h, 1, 2, 'first'); el = h.EdgeLabel; labeledge(h, 4, 7); el2 = h.EdgeLabel; "
           "layout(h, 'circle'); xc = h.XData; layout(h, 'subspace'); h.NodeCData = 1:5; ncol = h.NodeColor; s2 = findobj(gca, 'Type', 'scatter'); cd2 = s2.CData; "
           "h.XData = [0 1 2 3 4]; h.YData = [0 0 0 0 0]; xl = xlim;")
near('highlight: the nodes larger and red, held in NodeColor and MarkerSize', (W['sz'], W['ms'], W['nc'][[0, 1]]), ([[16, 36, 16, 36, 16]], [[4, 6, 4, 6, 4]], [[0, 0.447, 0.741], [1, 0, 0]]))
near('highlight of an edge: its own width and colour, in LineWidth and EdgeColor', (W['lw'], W['hw'], W['ec'][0]), ([[0.5, 4]], [[4, 0.5, 0.5, 0.5]], [0, 1, 0]))
same('labelnode and labeledge', (texts(W['nl']), texts(W['el']), texts(W['el2'])), (['start', '2', '3', '4', 'end'], ['first', '', '', ''], ['first', '', '', '7']))
near("layout 'circle'; NodeCData colours by the colormap (NodeColor 'flat')", (W['xc'], W['cd2']), ([0, np.sin(2 * np.pi / 5), np.sin(4 * np.pi / 5), -np.sin(4 * np.pi / 5), -np.sin(2 * np.pi / 5)], [[1, 2, 3, 4, 5]]), 1e-12)
same("NodeColor becomes 'flat'", W['ncol'].str(), 'flat')
near('XData and YData set move the nodes; the limits follow', W['xl'], [[-0.32, 4.32]], 1e-12)
raises("highlight(1, 2)", 'graph plot')
raises("G = graph([1 2], [2 3]); plot(G, 'Layout', 'spiral')", 'layout is')
raises("G = graph([1 2], [2 3]); plot(G, 'Fancy', 1)", 'not a property')
raises("G = graph([1 2], [2 3]); h = plot(G); h.MarkerSize = [1 2]", 'one for each of the 3')
raises("G = graph([1 2], [2 3]); h = plot(G); h.EdgeColor = [1 0 0; 0 1 0; 0 0 1]", 'a row for each of the 2')
raises("G = graph([1 2], [2 3]); h = plot(G); highlight(h, 1, 'Glow', 1)", "'glow' is not an option")

sys.exit(C.done())
