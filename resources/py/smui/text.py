"""Analyze > Text Explorer: the backend.

The words of a character column counted as JMP's Text Explorer counts
them, with scikit-learn's text features:

  tokens     the lowercase words of each text. Regex (JMP's default): the
             built-in patterns below (URLs, e-mail addresses, numbers, and
             words with inner apostrophes and hyphens, a possessive 's
             dropped), or the user's own pattern; Basic Words: runs of
             letters and digits. Words shorter or longer than the limits
             are left out.
  phrases    runs of 2 to Maximum Words per Phrase tokens of one text that
             neither begin nor end with a stop word, seen at least twice
  terms      the tokens with the added phrases joined, less the stop words
             (scikit-learn's ENGLISH_STOP_WORDS, read at run time, and the
             user's), stemmed by Porter's algorithm (written here from the
             1980 paper) and recoded; a stemmed term ends in a dot (·)
  DTM        scikit-learn's CountVectorizer over the terms of each document
             (a row, or the rows that share an ID), weighted as JMP weights
             it: Binary, Ternary, Frequency, Log Freq, TF IDF
  LSA        the truncated SVD of the weighted matrix: TruncatedSVD when it
             is not centered, PCA (the same SVD of the centered matrix,
             without making the sparse matrix dense) when it is
  topics     the SVD's term coordinates rotated by varimax (Kaiser 1958),
             as JMP's Topic Analysis; or scikit-learn's NMF or
             LatentDirichletAllocation

The functions between the '>>>' and '<<<' markers need only the standard
library, numpy, scipy and scikit-learn: the code under each result copies
them from this file, so that it computes the report's numbers exactly.
Everything that imports scikit-learn is registered with packages=SK, so
that the page loads it on the first call.
"""
import json
import math
import os
import re

import numpy as np

from . import data, predictive
from .registry import api

SK = predictive.SK
BASE, BAR = '#2f6690', '#8fa9c2'   # the points' and the bars' colours, light theme
STEMMING = ('none', 'combine', 'all')
TOKENIZING = ('regex', 'basic')
WEIGHTINGS = {'binary': 'Binary', 'ternary': 'Ternary', 'frequency': 'Frequency', 'logfreq': 'Log Freq', 'tfidf': 'TF IDF'}
CENTERING = {'uncentered': 'Uncentered', 'centered': 'Centered', 'scaled': 'Centered and Scaled'}
TOPIC_METHODS = {'varimax': 'Rotated SVD (varimax)', 'nmf': 'Non-negative Matrix Factorization', 'lda': 'Latent Dirichlet Allocation'}
MAX_PHRASE_WORDS = 12


def _dated(obj, table):
    """Code that reads the table's CSV (a string, or the strings of a list
    or dict) with the line that turns each date column it names back into
    the page's number, as dispatch does for the keys code and *_code."""
    from .util import date_columns, dated_code
    cols = date_columns(table)
    if not cols:
        return obj
    if isinstance(obj, str):
        return dated_code(obj, cols)
    if isinstance(obj, list):
        return [_dated(v, table) for v in obj]
    if isinstance(obj, dict):
        return {k: _dated(v, table) for k, v in obj.items()}
    return obj


# >>> reading the texts
DOT = '\u00b7'   # the mark of a stemmed term

REGEX_BUILTIN = (r"(?:https?://|www\.)[^\s<>\"']++"          # a URL
                 r"|[\w.+-]{1,64}+@[\w-]++(?:\.[\w-]++)++"    # an e-mail address
                 r"|\d++(?:[.,]\d++)*+%?+(?![^\W_])"          # a number: 12, 3.5, 1,000, 25%
                 r"|[^\W_]++(?:['\-][^\W_]++)*+")             # a word, with inner apostrophes and hyphens
REGEX_BASIC = r"[^\W_]++"                                     # Basic Words: runs of letters and digits


def read_terms(texts, stop_words, tokenizing='regex', regex=None, min_chars=1, max_chars=100,
               stemming='none', phrases=(), recodes=None, user_stop=()):
    """The tokens and the terms of each text, as Text Explorer reads them.

    tokens: the lowercase words of each text between min_chars and
    max_chars characters long (Regex: the built-in patterns, or regex;
    Basic Words: runs of letters and digits). terms: the tokens with the
    added phrases joined into one term each, less the stop words, stemmed
    by Porter's algorithm ('combine': the words that share a stem with
    another word; 'all': every word of three or more letters a-z) and
    recoded ({term: new term}). Returns (tokens, terms, stem_of), stem_of
    the stemmed term of each word that has one."""
    pattern = re.compile(regex or (REGEX_BUILTIN if tokenizing == 'regex' else REGEX_BASIC))
    builtin = tokenizing == 'regex' and not regex
    tokens = []
    for text in texts:
        toks = []
        if text:
            s = text.lower()
            if builtin:
                s = s.replace('\u2019', "'")
            found = pattern.findall(s) if not pattern.groups else [m.group(0) for m in pattern.finditer(s)]
            for t in found:
                if builtin:
                    if t.endswith("'s"):
                        t = t[:-2]                            # a possessive: customer's is customer
                    elif t.startswith(('http', 'www.')):
                        t = t.rstrip('.,;:!?)]}')             # a URL at the end of a sentence
                if t and min_chars <= len(t) <= max_chars:
                    toks.append(t)
        tokens.append(toks)
    joined = join_phrases(tokens, phrases)
    user_stop = set(user_stop)
    stem_of = {}
    if stemming in ('combine', 'all'):
        stemmer = PorterStemmer()
        words = {t for toks in joined for t in toks if t not in stop_words and t not in user_stop}
        stems = {w: stemmer.stem(w) for w in words if len(w) > 2 and w.isascii() and w.isalpha()}
        if stemming == 'all':
            stem_of = {w: s + DOT for w, s in stems.items()}
        else:
            by_stem = {}
            for w, s in stems.items():
                by_stem.setdefault(s, []).append(w)
            stem_of = {w: s + DOT for s, ws in by_stem.items() if len(ws) > 1 for w in ws}
    recodes = recodes or {}
    terms = []
    for toks in joined:
        out = []
        for t in toks:
            if t in stop_words or t in user_stop:
                continue
            d = stem_of.get(t, t)
            d = recodes.get(d, d)
            if d and d not in user_stop:
                out.append(d)
        terms.append(out)
    return tokens, terms, stem_of


def join_phrases(tokens, phrases):
    """Each added phrase (words and spaces) joined into one token where its
    words follow each other, the longest phrase first."""
    lead = {}
    for p in phrases:
        words = tuple(p.split())
        if len(words) > 1:
            lead.setdefault(words[0], []).append(words)
    if not lead:
        return tokens
    for v in lead.values():
        v.sort(key=len, reverse=True)
    joined = []
    for toks in tokens:
        out, i, n = [], 0, len(toks)
        while i < n:
            for ph in lead.get(toks[i], ()):
                if tuple(toks[i:i + len(ph)]) == ph:
                    out.append(' '.join(ph))
                    i += len(ph)
                    break
            else:
                out.append(toks[i])
                i += 1
        joined.append(out)
    return joined


def count_phrases(tokens, stop_words, max_words=4, most=1000):
    """The Phrase List: runs of 2 to max_words tokens of one text that
    neither begin nor end with a stop word, seen at least twice; the most
    frequent first (then alphabetically), at most `most` of them."""
    counts = {}
    for toks in tokens:
        n = len(toks)
        for i in range(n - 1):
            if toks[i] in stop_words:
                continue
            for j in range(i + 2, min(n, i + max_words) + 1):
                if toks[j - 1] not in stop_words:
                    key = ' '.join(toks[i:j])
                    counts[key] = counts.get(key, 0) + 1
    kept = sorted((p for p, c in counts.items() if c > 1), key=lambda p: (-counts[p], p))
    return [(p, counts[p]) for p in kept[:most]]
# <<< reading the texts


# >>> the Porter stemmer
class PorterStemmer:
    """Porter's suffix stripping for English, as published: M. F. Porter,
    An algorithm for suffix stripping, Program 14 (3), 130-137, 1980.
    A word of one or two letters is left as it is, as Porter's own
    implementation leaves it."""

    STEP2 = (('ational', 'ate'), ('tional', 'tion'), ('enci', 'ence'), ('anci', 'ance'), ('izer', 'ize'),
             ('abli', 'able'), ('alli', 'al'), ('entli', 'ent'), ('eli', 'e'), ('ousli', 'ous'),
             ('ization', 'ize'), ('ation', 'ate'), ('ator', 'ate'), ('alism', 'al'), ('iveness', 'ive'),
             ('fulness', 'ful'), ('ousness', 'ous'), ('aliti', 'al'), ('iviti', 'ive'), ('biliti', 'ble'))
    STEP3 = (('icate', 'ic'), ('ative', ''), ('alize', 'al'), ('iciti', 'ic'), ('ical', 'ic'), ('ful', ''), ('ness', ''))
    STEP4 = ('al', 'ance', 'ence', 'er', 'ic', 'able', 'ible', 'ant', 'ement', 'ment', 'ent', 'ion', 'ou',
             'ism', 'ate', 'iti', 'ous', 'ive', 'ize')

    def __init__(self):
        # of each group of rules only the one with the longest matching suffix is obeyed
        self.step2_rules = sorted(self.STEP2, key=lambda r: -len(r[0]))
        self.step3_rules = sorted(self.STEP3, key=lambda r: -len(r[0]))
        self.step4_rules = sorted(self.STEP4, key=len, reverse=True)
        self.memo = {}

    @staticmethod
    def consonants(w):
        """Where w has a consonant: a letter other than a, e, i, o and u,
        and other than y preceded by a consonant."""
        out = []
        for i, c in enumerate(w):
            out.append(c not in 'aeiou' and (c != 'y' or i == 0 or not out[i - 1]))
        return out

    def measure(self, s):
        """m of [C](VC)^m[V]: the number of vowel-consonant sequences."""
        m, after_vowel = 0, False
        for c in self.consonants(s):
            if c and after_vowel:
                m += 1
            after_vowel = not c
        return m

    def has_vowel(self, s):                  # *v*
        return not all(self.consonants(s))

    def double_consonant(self, s):           # *d
        return len(s) > 1 and s[-1] == s[-2] and self.consonants(s)[-1]

    def cvc(self, s):                        # *o: consonant-vowel-consonant, the last not w, x or y
        if len(s) < 3:
            return False
        c = self.consonants(s)
        return c[-3] and not c[-2] and c[-1] and s[-1] not in 'wxy'

    def step1a(self, w):
        if w.endswith(('sses', 'ies')):
            return w[:-2]
        if w.endswith('ss'):
            return w
        return w[:-1] if w.endswith('s') else w

    def step1b(self, w):
        if w.endswith('eed'):
            return w[:-1] if self.measure(w[:-3]) > 0 else w
        for suffix in ('ed', 'ing'):
            if w.endswith(suffix):
                s = w[:-len(suffix)]
                if not self.has_vowel(s):
                    return w
                if s.endswith(('at', 'bl', 'iz')):
                    return s + 'e'
                if self.double_consonant(s) and s[-1] not in 'lsz':
                    return s[:-1]
                if self.measure(s) == 1 and self.cvc(s):
                    return s + 'e'
                return s
        return w

    def step1c(self, w):
        return w[:-1] + 'i' if w.endswith('y') and self.has_vowel(w[:-1]) else w

    def _replace(self, w, rules):
        for suffix, new in rules:
            if w.endswith(suffix):
                s = w[:-len(suffix)]
                return s + new if self.measure(s) > 0 else w
        return w

    def step2(self, w):
        return self._replace(w, self.step2_rules)

    def step3(self, w):
        return self._replace(w, self.step3_rules)

    def step4(self, w):
        for suffix in self.step4_rules:
            if w.endswith(suffix):
                s = w[:-len(suffix)]
                ok = self.measure(s) > 1 and (suffix != 'ion' or s.endswith(('s', 't')))
                return s if ok else w
        return w

    def step5a(self, w):
        if w.endswith('e'):
            s = w[:-1]
            m = self.measure(s)
            if m > 1 or (m == 1 and not self.cvc(s)):
                return s
        return w

    def step5b(self, w):
        return w[:-1] if w.endswith('ll') and self.measure(w) > 1 else w

    def stem(self, word):
        """The stem of a lowercase word of the letters a-z (any other word
        is left as it is)."""
        s = self.memo.get(word)
        if s is None:
            s = word
            if len(word) > 2 and word.isascii() and word.isalpha() and word.islower():
                for step in (self.step1a, self.step1b, self.step1c, self.step2, self.step3, self.step4, self.step5a, self.step5b):
                    s = step(s)
            self.memo[word] = s
        return s
# <<< the Porter stemmer


# >>> the document term matrix
def weigh(X, weighting):
    """JMP's weightings of a document term matrix of counts X (scipy
    sparse, documents by terms): Binary 1 when the term is in the document;
    Ternary 2 when it is there more than once, 1 once; Frequency its count;
    Log Freq log10(1 + count); TF IDF count * log(documents / documents
    with the term)."""
    import scipy.sparse as sp
    X = sp.csr_matrix(X, dtype=float, copy=True)
    if weighting == 'binary':
        X.data[:] = 1.0
    elif weighting == 'ternary':
        X.data = np.where(X.data > 1, 2.0, 1.0)
    elif weighting == 'logfreq':
        X.data = np.log10(1.0 + X.data)
    elif weighting == 'tfidf':
        with_term = np.bincount(X.indices, minlength=X.shape[1])
        X = sp.csr_matrix(X @ sp.diags(np.log(X.shape[0] / np.maximum(with_term, 1))))
    return X


def lsa_svd(X, k, centering='centered', seed=0):
    """The first k singular values of the weighted matrix X and the
    coordinates of the documents (U S = X V) and of the terms (V S), as
    latent semantic analysis compares them (Deerwester et al. 1990).
    Uncentered: scikit-learn's TruncatedSVD of X. Centered, or centered
    and scaled (each term divided by its standard deviation): PCA, the SVD
    of the centered matrix, computed without making X dense. Each vector's
    sign makes its largest term coordinate positive. Returns (documents,
    terms, singular values, the matrix's total sum of squares)."""
    import scipy.sparse as sp
    from sklearn.decomposition import PCA, TruncatedSVD
    X = sp.csr_matrix(X, dtype=float)
    n, m = X.shape
    if centering == 'uncentered':
        model = TruncatedSVD(n_components=k, algorithm='arpack', random_state=seed)
        total = float(X.multiply(X).sum())
    else:
        mean = np.asarray(X.mean(axis=0)).ravel()
        if centering == 'scaled':
            var = (np.asarray(X.multiply(X).mean(axis=0)).ravel() - mean ** 2) * n / (n - 1)
            sd = np.sqrt(np.maximum(var, 0.0))
            sd[sd <= 1e-12 * max(1.0, float(sd.max()))] = 1.0
            X = sp.csr_matrix(X @ sp.diags(1.0 / sd))
            mean = mean / sd
        model = PCA(n_components=k, svd_solver='covariance_eigh' if m <= 1500 else 'arpack', random_state=seed)
        total = float(X.multiply(X).sum() - n * np.sum(mean ** 2))
    docs = model.fit_transform(X)
    s = model.singular_values_
    terms = model.components_.T * s
    flip = np.sign(terms[np.abs(terms).argmax(axis=0), np.arange(terms.shape[1])])
    flip[flip == 0] = 1.0
    return docs * flip, terms * flip, s, total
# <<< the document term matrix


# >>> the topics
def varimax(L, normalize=True, eps=1e-5, max_iter=1000):
    """Kaiser's varimax rotation of the loadings L (terms by topics), by the
    algorithm of R's stats::varimax: rows normalized to length 1 first
    (Kaiser's normalization) when normalize. Returns (the rotated loadings,
    the rotation)."""
    L = np.asarray(L, dtype=float)
    p, k = L.shape
    if k < 2:
        return L.copy(), np.eye(k)
    h = np.sqrt((L ** 2).sum(axis=1)) if normalize else np.ones(p)
    h = np.where(h > 0, h, 1.0)
    A = L / h[:, None]
    R = np.eye(k)
    d = 0.0
    for _ in range(max_iter):
        Z = A @ R
        u, sv, vt = np.linalg.svd(A.T @ (Z ** 3 - Z * ((Z ** 2).sum(axis=0) / p)))
        R = u @ vt
        d_old, d = d, float(sv.sum())
        if d < d_old * (1 + eps):
            break
    return (A @ R) * h[:, None], R


def varimax_topics(docs, terms, s):
    """Topics as JMP's Topic Analysis makes them: the first k term
    coordinates of the SVD (V S) rotated by varimax. The loadings are V S R
    / sqrt(n - 1) (with centering, the covariances of the terms with the
    topics; centered and scaled, their correlations); the scores sqrt(n - 1)
    U R (with centering, mean 0 and variance 1), so that scores times
    loadings is the SVD's rank-k fit. Largest topic first, each signed so
    that its largest loading is positive."""
    n = docs.shape[0]
    _, R = varimax(terms)
    load = terms @ R / np.sqrt(n - 1)
    scores = (docs / np.where(s > 0, s, 1.0)) @ R * np.sqrt(n - 1)
    order = np.argsort(-(load ** 2).sum(axis=0), kind='stable')
    load, scores = load[:, order], scores[:, order]
    flip = np.sign(load[np.abs(load).argmax(axis=0), np.arange(load.shape[1])])
    flip[flip == 0] = 1.0
    return load * flip, scores * flip, R[:, order] * flip
# <<< the topics


# ---------------------------------------------------------------------------
# the report's settings, and the documents of a column
# ---------------------------------------------------------------------------

def _int(v, name, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{name} is a whole number, not {v!r}')
    if not math.isfinite(x) or x != int(x) or not lo <= x <= hi:
        raise ValueError(f'{name} is a whole number from {lo} to {hi}')
    return int(x)


def _words(v):
    """A term as the user gives it: lowercase, single spaces."""
    return ' '.join(str(v).lower().split())


def _config(language='english', max_words=4, max_phrases=1000, min_chars=1, max_chars=100, stemming='none',
            tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=()):
    if str(language or 'english').lower() != 'english':
        raise ValueError('Text Explorer reads English here (its stop words and its stemmer are English)')
    cfg = {
        'max_words': _int(max_words, 'Maximum Words per Phrase', 1, MAX_PHRASE_WORDS),
        'max_phrases': _int(max_phrases, 'Maximum Number of Phrases', 0, 100000),
        'min_chars': _int(min_chars, 'Minimum Characters per Word', 1, 1000),
        'max_chars': _int(max_chars, 'Maximum Characters per Word', 1, 100000),
        'stemming': stemming if stemming in STEMMING else None,
        'tokenizing': tokenizing if tokenizing in TOKENIZING else None,
        'regex': (regex or '').strip() or None,
    }
    if cfg['stemming'] is None:
        raise ValueError(f'Stemming is one of {", ".join(STEMMING)}, not {stemming!r}')
    if cfg['tokenizing'] is None:
        raise ValueError(f'Tokenizing is regex or basic, not {tokenizing!r}')
    if cfg['max_chars'] < cfg['min_chars']:
        raise ValueError('Maximum Characters per Word is less than the minimum')
    if cfg['regex']:
        if cfg['tokenizing'] != 'regex':
            cfg['regex'] = None
        else:
            try:
                re.compile(cfg['regex'])
            except re.error as e:
                raise ValueError(f'the regular expression does not compile: {e}')
    cfg['stop_add'] = sorted({_words(w) for w in (stop_add or []) if _words(w)})
    cfg['recodes'] = {_words(a): _words(b) for a, b in sorted((recodes or {}).items()) if _words(a)}
    cfg['phrases'] = sorted({_words(p) for p in (phrases or []) if len(_words(p).split()) > 1})
    return cfg


def _read_kwargs(cfg):
    return {'tokenizing': cfg['tokenizing'], 'regex': cfg['regex'], 'min_chars': cfg['min_chars'], 'max_chars': cfg['max_chars'],
            'stemming': cfg['stemming'], 'phrases': cfg['phrases'], 'recodes': cfg['recodes'], 'user_stop': cfg['stop_add']}


class Corpus:
    """The documents of one column in the report's rows: the rows, the
    documents they make, each row's tokens and terms, and the counts."""


def _documents(table, column, rows, id_col):
    """The texts of the report's rows and the documents they make: each row
    one, or with an ID column the rows that share an ID."""
    m = data.meta(table, column)
    if m.get('dataType') == 'numeric':
        raise ValueError(f'{column} is numeric: Text Explorer reads character columns')
    idx = np.arange(data.TABLES[table]['n']) if rows is None else np.asarray(rows, dtype=int)
    raw = data.raw(table, column, idx)
    texts = [v if isinstance(v, str) else '' for v in raw]
    notes = []
    if not id_col:
        return idx, texts, [[i] for i in range(len(idx))], [None] * len(idx), notes
    if id_col == column:
        raise ValueError('the ID column is the text column')
    ids = data.raw(table, id_col, idx)
    numeric = data.meta(table, id_col).get('dataType') == 'numeric'
    keys = []
    for v in ids:
        if numeric:
            keys.append(None if v is None or not math.isfinite(float(v)) else float(v))
        else:
            keys.append(v if isinstance(v, str) and v != '' else None)
    keep = [i for i, k in enumerate(keys) if k is not None]
    if len(keep) < len(keys):
        notes.append(f'{len(keys) - len(keep)} rows with no {id_col} are left out.')
    idx = idx[keep]
    texts = [texts[i] for i in keep]
    keys = [keys[i] for i in keep]
    pos, docs, labels = {}, [], []
    for i, k in enumerate(keys):
        if k not in pos:
            pos[k] = len(docs)
            docs.append([])
            labels.append(predictive.level_label(k))
        docs[pos[k]].append(i)
    return idx, texts, docs, labels, notes


def _corpus(table, column, rows, id_col, cfg):
    def build():
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer
        C = Corpus()
        C.rows, C.texts, C.docs, C.labels, C.notes = _documents(table, column, rows, id_col)
        C.stop = ENGLISH_STOP_WORDS
        C.tokens, C.terms, C.stem_of = read_terms(C.texts, ENGLISH_STOP_WORDS, **_read_kwargs(cfg))
        doc_terms = C.terms if not id_col else [[t for i in d for t in C.terms[i]] for d in C.docs]
        C.n_docs = len(doc_terms)
        if any(doc_terms):
            vec = CountVectorizer(analyzer=_as_is)
            C.X = vec.fit_transform(doc_terms).tocsr()
            C.vocab = vec.get_feature_names_out()
        else:
            import scipy.sparse as sp
            C.X = sp.csr_matrix((C.n_docs, 0), dtype=np.int64)
            C.vocab = np.array([], dtype=object)
        C.counts = np.asarray(C.X.sum(axis=0)).ravel().astype(np.int64)
        C.with_term = np.bincount(C.X.indices, minlength=C.X.shape[1]).astype(np.int64)
        C.order = np.lexsort((C.vocab.astype(str), -C.counts)) if len(C.vocab) else np.array([], dtype=int)
        C.index = {t: j for j, t in enumerate(C.vocab)}
        return C
    spec = {'column': column, 'id': id_col, **cfg}
    return predictive.cached('text.corpus', table, rows, spec, build)


def _progress(model, what, total):
    """A 'smui:progress' line after each EM iteration of a fit (the page
    shows it while LDA runs): the model's own step, wrapped; the numbers
    are the same. Nothing happens if scikit-learn names its step otherwise."""
    step = getattr(model, '_em_step', None)
    if step is None:
        return
    done = [0]

    def counted(*args, **kwargs):
        out = step(*args, **kwargs)
        done[0] += 1
        print(f'smui:progress {what} {done[0]} {total}', flush=True)
        return out
    model._em_step = counted


def _as_is(terms):
    """CountVectorizer's analyzer: each document is its list of terms already."""
    return terms


def _chosen(C, min_freq, max_terms, terms=None):
    """The columns of the document term matrix: the given terms, or the most
    frequent ones with at least min_freq occurrences (ties alphabetically)."""
    if terms:
        cols = [C.index[t] for t in dict.fromkeys(terms) if t in C.index]
    else:
        cols = [int(j) for j in C.order if C.counts[j] >= min_freq][:max_terms]
    return cols


# ---------------------------------------------------------------------------
# the code under the report
# ---------------------------------------------------------------------------

_SOURCE = None


def _block(name):
    """The lines between '# >>> name' and '# <<< name' in this file."""
    global _SOURCE
    if _SOURCE is None:
        with open(os.path.abspath(__file__), encoding='utf-8') as f:
            _SOURCE = f.read()
    a = _SOURCE.index(f'# >>> {name}\n') + len(f'# >>> {name}\n')
    return _SOURCE[a:_SOURCE.index(f'# <<< {name}\n')].rstrip()


def _py(v):
    return json.dumps(v, ensure_ascii=False)


def _lit(v):
    """A value as a Python literal: 12.0 as 12, text quoted."""
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        f = float(v)
        return str(int(f)) if f.is_integer() and abs(f) < 1e15 else repr(f)
    return _py(str(v))


def _keep_lines(table, rows, where=None):
    """After the code's read_csv line: the By group's rows (its where lines:
    a character By column is read as text, a numeric one compared as a
    number) and, of those, the ones the report uses (excluded and filtered
    rows dropped)."""
    L = []
    n = data.TABLES[table]['n'] if table in data.TABLES else 0
    match = np.ones(n, dtype=bool)
    for w in where or []:
        v = data.raw(table, w['column'])
        num = data.meta(table, w['column']).get('dataType') == 'numeric'
        match &= (np.asarray(v, dtype=float) == float(w['value'])) if num else np.array([x == w['value'] for x in v], dtype=bool)
        shown = w['value'] if isinstance(w['value'], str) else _lit(w['value'])
        test = f'pd.to_numeric(df[{_py(w["column"])}], errors="coerce") == {_lit(w["value"])}' if num else f'df[{_py(w["column"])}] == {_lit(w["value"])}'
        L.append(f'df = df[{test}]   # only the rows where {w["column"]} is {shown}')
    if rows is not None and n:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.flatnonzero(match & ~keep).tolist()
        if drop and not where and keep.sum() <= n / 2:
            return [f'df = df.loc[{np.flatnonzero(keep).tolist()}]   # the rows of the report']
        if drop:
            L.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
    return L


def _code_head(table, table_name, column, rows, id_col, cfg, extra_imports=(), where=None, keep_every=False):
    """Read the exported table, keep the report's rows, and read the texts
    as the report does: the lines up to the terms of every document.
    keep_every: with an ID, keep the report's rows before the rows without
    one are left out (as every), for the word cloud's By Column colouring."""
    dtypes = {column: 'str'}
    if id_col:
        dtypes[id_col] = 'str'
    for w in where or []:
        if data.meta(table, w['column']).get('dataType') != 'numeric':
            dtypes[w['column']] = 'str'
    L = ['import re', 'import numpy as np', 'import pandas as pd',
         'from sklearn.feature_extraction.text import CountVectorizer, ENGLISH_STOP_WORDS', *extra_imports, '',
         f'df = pd.read_csv({_py(table_name + ".csv")}, dtype={_py(dtypes)}, keep_default_na=False)   # the table as File > Export CSV writes it; the text as it is']
    L += _keep_lines(table, rows, where)
    if id_col:
        if keep_every:
            L.append('every = df   # the report\'s rows, with an ID or without')
        L.append(f'df = df[df[{_py(id_col)}] != ""]   # the rows with an ID')
    L += ['', _block('reading the texts'), '']
    if cfg['stemming'] != 'none':
        L += [_block('the Porter stemmer'), '']
    args = [f'tokenizing={_py(cfg["tokenizing"])}']
    if cfg['regex']:
        args.append(f'regex={_py(cfg["regex"])}')
    args += [f'min_chars={cfg["min_chars"]}', f'max_chars={cfg["max_chars"]}', f'stemming={_py(cfg["stemming"])}']
    if cfg['phrases']:
        args.append(f'phrases={_py(cfg["phrases"])}')
    if cfg['recodes']:
        args.append(f'recodes={_py(cfg["recodes"])}')
    if cfg['stop_add']:
        args.append(f'user_stop={_py(cfg["stop_add"])}')
    L += [f'texts = df[{_py(column)}].tolist()',
          f'tokens, terms, stem_of = read_terms(texts, ENGLISH_STOP_WORDS, {", ".join(args)})']
    if id_col:
        L += [f'ids = df[{_py(id_col)}].tolist()',
              'docs = {}   # the rows that share an ID are one document, in the order they first come',
              'for key, t in zip(ids, terms):',
              '    docs.setdefault(key, []).extend(t)',
              'documents = list(docs.values())']
    else:
        L.append('documents = terms   # each row is a document')
    L += ['vec = CountVectorizer(analyzer=lambda terms: terms)   # the documents are lists of terms already',
          'X = vec.fit_transform(documents)   # documents by terms: counts',
          'counts = np.asarray(X.sum(axis=0)).ravel()',
          'term_list = pd.DataFrame({"Term": vec.get_feature_names_out(), "Count": counts}).sort_values(["Count", "Term"], ascending=[False, True], ignore_index=True)']
    return L


def _code_dtm_columns(min_freq, max_terms, terms=None):
    if terms:
        return [f'chosen = {_py(list(terms))}',
                'cols = [vec.vocabulary_[t] for t in chosen]']
    return [f'chosen = term_list[term_list["Count"] >= {min_freq}]["Term"].head({max_terms}).tolist()   # the most frequent terms',
            'cols = [vec.vocabulary_[t] for t in chosen]']


# ---------------------------------------------------------------------------
# the entry points
# ---------------------------------------------------------------------------

def _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases):
    return _config(language=language, max_words=max_words, max_phrases=max_phrases, min_chars=min_chars, max_chars=max_chars,
                   stemming=stemming, tokenizing=tokenizing, regex=regex, stop_add=stop_add, recodes=recodes, phrases=phrases)


@api('text.explore', packages=SK)
def explore(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=1000, min_chars=1, max_chars=100,
            stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), where=None, table_name='data'):
    """Summary Counts, the Term List and the Phrase List of a column, with
    the rows that hold each term and phrase (for linking), the stems, and
    the stop words; the code, and the lines the word cloud's code starts
    with (cloud_head: the page adds its layout)."""
    try:
        cfg = _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases)
        C = _corpus(table, column, rows, id_col, cfg)
    except ValueError as e:
        return {'error': str(e)}
    n = C.n_docs
    total = int(C.counts.sum())
    nonempty = int((C.X.getnnz(axis=1) > 0).sum()) if n else 0
    summary = {'terms': int(len(C.vocab)), 'cases': n, 'tokens': total, 'tokens_per_case': total / n if n else None,
               'portion_nonempty': nonempty / n if n else None, 'nonempty': nonempty}
    # the rows that hold each term
    at = {}
    for i, ts in enumerate(C.terms):
        r = int(C.rows[i])
        for t in dict.fromkeys(ts):
            at.setdefault(t, []).append(r)
    terms = [{'term': str(C.vocab[j]), 'count': int(C.counts[j]), 'cases': int(C.with_term[j])} for j in C.order]
    term_rows = [at.get(str(C.vocab[j]), []) for j in C.order]
    # the phrases, and the rows that hold each
    stop = C.stop | set(cfg['stop_add'])
    plist = count_phrases(C.tokens, stop, cfg['max_words'], cfg['max_phrases']) if cfg['max_words'] > 1 else []
    kept = {p: k for k, (p, _) in enumerate(plist)}
    prow = [[] for _ in plist]
    if kept:
        mw = cfg['max_words']
        for i, toks in enumerate(C.tokens):
            seen = set()
            nt = len(toks)
            for a in range(nt - 1):
                if toks[a] in stop:
                    continue
                for b in range(a + 2, min(nt, a + mw) + 1):
                    if toks[b - 1] not in stop:
                        k = kept.get(' '.join(toks[a:b]))
                        if k is not None and k not in seen:
                            seen.add(k)
                            prow[k].append(int(C.rows[i]))
    phrases_out = [{'phrase': p, 'count': c, 'n': len(p.split())} for p, c in plist]
    # the words behind each term (stems, recodes, phrases): for Show Text and the Stem Report
    word_counts = {}
    for toks in join_phrases(C.tokens, cfg['phrases']):
        for t in toks:
            word_counts[t] = word_counts.get(t, 0) + 1
    forms = {}
    user_stop = set(cfg['stop_add'])
    for w, c in word_counts.items():
        if w in C.stop or w in user_stop:
            continue
        d = C.stem_of.get(w, w)
        d = cfg['recodes'].get(d, d)
        if d in C.index and d != w:
            forms.setdefault(d, []).append([w, c])
    for v in forms.values():
        v.sort(key=lambda x: (-x[1], x[0]))
    stems = []
    if cfg['stemming'] != 'none':
        by = {}
        for w, s in C.stem_of.items():
            by.setdefault(s, []).append([w, word_counts.get(w, 0)])
        for s, ws in by.items():
            ws.sort(key=lambda x: (-x[1], x[0]))
            stems.append({'stem': s, 'count': int(sum(c for _, c in ws)), 'forms': ws})
        stems.sort(key=lambda x: (-x['count'], x['stem']))
    empty = sum(1 for t in C.texts if not t.strip())
    notes = list(C.notes)
    if empty:
        notes.append(f'{empty} of the {len(C.texts)} rows have no text.')
    code = _code_head(table, table_name, column, rows, id_col, cfg, where=where) + [
        'summary = {"Number of Terms": X.shape[1], "Number of Cases": X.shape[0], "Total Tokens": int(X.sum()),',
        '           "Tokens per Case": X.sum() / X.shape[0], "Portion Non-empty": float(np.mean(X.getnnz(axis=1) > 0))}',
        f'stop = ENGLISH_STOP_WORDS | set({_py(cfg["stop_add"])})' if cfg['stop_add'] else 'stop = ENGLISH_STOP_WORDS',
        f'phrase_list = pd.DataFrame(count_phrases(tokens, stop, max_words={cfg["max_words"]}, most={cfg["max_phrases"]}), columns=["Phrase", "Count"])',
        'phrase_list["N"] = [len(p.split()) for p in phrase_list["Phrase"]]   # the words in the phrase',
        'print(pd.Series(summary).to_string())',
        'print(term_list.head(20).to_string(index=False))',
        'print(phrase_list.head(20).to_string(index=False))',
    ]
    return {'column': column, 'id': id_col, 'n_rows': len(C.texts), 'summary': summary, 'terms': terms, 'term_rows': term_rows,
            'phrases': phrases_out, 'phrase_rows': prow, 'forms': forms, 'stems': stems, 'doc_labels': C.labels if id_col else None,
            'stop_words': sorted(C.stop), 'user_stop': cfg['stop_add'], 'recodes': cfg['recodes'], 'added_phrases': cfg['phrases'],
            'settings': cfg, 'notes': notes, 'code': '\n'.join(code),
            'cloud_head': _dated('\n'.join(_code_head(table, table_name, column, rows, id_col, cfg, ['import matplotlib.pyplot as plt'], where, keep_every=True)), table)}


def _dtm_spec(weighting, min_freq, max_terms):
    if weighting not in WEIGHTINGS:
        raise ValueError(f'the weighting is one of {", ".join(WEIGHTINGS)}, not {weighting!r}')
    return _int(min_freq, 'Minimum Term Frequency', 1, 10 ** 9), _int(max_terms, 'Maximum Number of Terms', 1, 100000)


def _svd(table, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, k, seed):
    """The SVD of the weighted document term matrix, remembered for the
    Save commands. k is cut to the matrix's size."""
    C = _corpus(table, column, rows, id_col, cfg)
    cols = _chosen(C, min_freq, max_terms)
    n = C.n_docs
    if len(cols) < 2:
        raise ValueError(f'{len(cols)} term{"" if len(cols) == 1 else "s"} occur{"s" if len(cols) == 1 else ""} at least {min_freq} times: the SVD needs two or more')
    if n < 3:
        raise ValueError('the SVD needs three or more documents')
    k = max(1, min(int(k), n - 1, len(cols) - 1))

    def build():
        Xw = weigh(C.X[:, cols], weighting)
        docs, terms, s, total = lsa_svd(Xw, k, centering, seed)
        return {'cols': cols, 'docs': docs, 'terms': terms, 's': s, 'total': total, 'k': k}
    spec = {'column': column, 'id': id_col, **cfg, 'weighting': weighting, 'centering': centering, 'min_freq': min_freq,
            'max_terms': max_terms, 'k': k, 'seed': seed}
    return C, predictive.cached('text.svd', table, rows, spec, build)


def _lsa_code(table, table_name, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, k, seed, where=None, extra_imports=()):
    L = _code_head(table, table_name, column, rows, id_col, cfg, extra_imports, where) + [''] + [_block('the document term matrix'), ''] + _code_dtm_columns(min_freq, max_terms) + [
        f'Xw = weigh(X[:, cols], {_py(weighting)})   # {WEIGHTINGS[weighting]}',
        f'docs, terms, s, total = lsa_svd(Xw, k={k}, centering={_py(centering)}, seed={int(seed)})   # {CENTERING[centering]}',
    ]
    return L


@api('text.lsa', packages=SK)
def lsa(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=1000, min_chars=1, max_chars=100,
        stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), weighting='tfidf',
        centering='centered', min_freq=4, max_terms=1000, k=100, seed=0, show=2, where=None, table_name='data'):
    """Latent Semantic Analysis: the singular values, and the first `show`
    coordinates of every document and of every term of the matrix; the code,
    the singular values' bar chart's (plot_code) and the lines the SVD
    plots' code starts with (svd_head: the page adds the drawing)."""
    try:
        cfg = _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases)
        min_freq, max_terms = _dtm_spec(weighting, min_freq, max_terms)
        if centering not in CENTERING:
            raise ValueError(f'the centering is one of {", ".join(CENTERING)}, not {centering!r}')
        k = _int(k, 'Number of Singular Vectors', 1, 100000)
        seed = int(predictive.seed_of(seed) or 0)
        C, S = _svd(table, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, k, seed)
    except ValueError as e:
        return {'error': str(e)}
    k = S['k']
    show = max(1, min(int(show), k))
    s, total = S['s'], S['total']
    pct = 100 * s ** 2 / total if total > 0 else np.full(len(s), np.nan)
    singular = [{'number': i + 1, 'value': float(s[i]), 'percent': float(pct[i]), 'cum': float(np.sum(pct[:i + 1]))} for i in range(k)]
    doc_rows = [[int(C.rows[i]) for i in d] for d in C.docs]
    code = _lsa_code(table, table_name, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, k, seed, where) + [
        'pct = 100 * s ** 2 / total   # the share of the matrix\'s sum of squares',
        'singular_values = pd.DataFrame({"Number": np.arange(1, len(s) + 1), "Singular Value": s, "Percent": pct, "Cum Percent": np.cumsum(pct)})',
        'print(singular_values.head(10).to_string(index=False))',
        'print(pd.DataFrame(terms[:, :2], index=chosen, columns=["Term Vec1", "Term Vec2"]).head(10))',
    ]
    head = _lsa_code(table, table_name, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, k, seed, where, ['import matplotlib.pyplot as plt'])
    top = min(30, k)
    bars = head + [
        'pct = 100 * s ** 2 / total   # each singular value\'s share of the matrix\'s sum of squares',
        f'top = min(30, len(s))   # the first {top}',
        f'fig, ax = plt.subplots(figsize=(2.8, {max(140, 13 * top + 50) / 100:g}), layout="constrained")',
        f'ax.barh(np.arange(1, top + 1), pct[:top], height=0.8, color="{BAR}")',
        'ax.invert_yaxis()   # the first at the top',
        f'ax.set_yticks({"np.arange(5, top + 1, 5)" if top > 15 else "np.arange(1, top + 1)"})',
        'ax.set_xlim(left=0)', 'ax.set_xlabel("Percent")', 'ax.set_title("Singular values, percent")', 'plt.show()']
    return {'column': column, 'k': k, 'n_docs': C.n_docs, 'n_terms': len(S['cols']), 'weighting': weighting, 'centering': centering,
            'min_freq': min_freq, 'max_terms': max_terms, 'seed': seed, 'total': total,
            'plot_code': _dated({'singular': '\n'.join(bars)}, table), 'svd_head': _dated('\n'.join(head), table),
            'solver': 'TruncatedSVD (arpack)' if centering == 'uncentered' else f'PCA ({"covariance_eigh" if len(S["cols"]) <= 1500 else "arpack"})',
            'singular': singular, 'terms': [str(C.vocab[j]) for j in S['cols']], 'term_counts': [int(C.counts[j]) for j in S['cols']],
            'docs': S['docs'][:, :show].T.tolist(), 'term_vectors': S['terms'][:, :show].T.tolist(), 'doc_rows': doc_rows,
            'doc_labels': C.labels if id_col else None, 'code': '\n'.join(code)}


@api('text.topics', packages=SK)
def topics(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=1000, min_chars=1, max_chars=100,
           stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), method='varimax',
           n_topics=10, weighting='tfidf', centering='centered', min_freq=4, max_terms=1000, seed=0, top=10, scores=2,
           where=None, table_name='data'):
    """Topic Analysis: varimax-rotated SVD (JMP's), or NMF or LDA. The top
    terms of each topic, every term's loadings, the variance of each topic
    and the first `scores` topic scores of every document."""
    try:
        cfg = _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases)
        if method not in TOPIC_METHODS:
            raise ValueError(f'the method is one of {", ".join(TOPIC_METHODS)}, not {method!r}')
        if method == 'lda':
            weighting = 'frequency'
        min_freq, max_terms = _dtm_spec(weighting, min_freq, max_terms)
        if centering not in CENTERING:
            raise ValueError(f'the centering is one of {", ".join(CENTERING)}, not {centering!r}')
        k = _int(n_topics, 'Number of Topics', 1, 1000)
        seed = int(predictive.seed_of(seed) or 0)
        top = _int(top, 'the top terms', 1, 1000)
        if method == 'varimax':
            C, S = _svd(table, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, k, seed)
            k = S['k']
        else:
            C = _corpus(table, column, rows, id_col, cfg)
            cols = _chosen(C, min_freq, max_terms)
            if len(cols) < 2 or C.n_docs < 3:
                raise ValueError('the topics need two or more terms and three or more documents')
            k = max(1, min(k, C.n_docs - 1, len(cols) - 1))
    except ValueError as e:
        return {'error': str(e)}
    if method == 'varimax':
        cols = S['cols']

        def build():
            load, sc, R = varimax_topics(S['docs'], S['terms'], S['s'])
            return {'load': load, 'scores': sc, 'variance': (load ** 2).sum(axis=0) * (C.n_docs - 1)}
        spec = {'column': column, 'id': id_col, **cfg, 'weighting': weighting, 'centering': centering, 'min_freq': min_freq,
                'max_terms': max_terms, 'k': k, 'seed': seed}
        T = predictive.cached('text.varimax', table, rows, spec, build)
        total = S['total']
    else:
        def build():
            from sklearn.decomposition import NMF, LatentDirichletAllocation
            Xw = weigh(C.X[:, cols], weighting)
            if method == 'nmf':
                model = NMF(n_components=k, init='nndsvda', max_iter=500, random_state=seed)
                sc = model.fit_transform(Xw)
                load = model.components_.T
                size = sc.sum(axis=0) * load.sum(axis=0)
            else:
                model = LatentDirichletAllocation(n_components=k, learning_method='batch', random_state=seed)
                _progress(model, 'lda', model.max_iter)
                sc = model.fit_transform(Xw)
                load = (model.components_ / model.components_.sum(axis=1, keepdims=True)).T
                size = sc.sum(axis=0)
            order = np.argsort(-size, kind='stable')
            return {'load': load[:, order], 'scores': sc[:, order], 'variance': size[order]}
        spec = {'column': column, 'id': id_col, **cfg, 'weighting': weighting, 'min_freq': min_freq, 'max_terms': max_terms,
                'k': k, 'seed': seed, 'method': method}
        T = predictive.cached(f'text.{method}', table, rows, spec, build)
        total = float(np.sum(T['variance']))
    load = T['load']
    names = [str(C.vocab[j]) for j in cols]
    tops = []
    for t in range(k):
        o = np.argsort(-load[:, t], kind='stable')[:top]
        tops.append([{'term': names[j], 'loading': float(load[j, t])} for j in o])
    var = np.asarray(T['variance'], dtype=float)
    pct = 100 * var / total if total > 0 else np.full(k, np.nan)
    ns = max(0, min(int(scores or 0), k))
    def with_head(extra_imports=()):
        return _code_head(table, table_name, column, rows, id_col, cfg, extra_imports, where) + ['', _block('the document term matrix'), '']
    head = with_head()
    if method == 'varimax':
        code = head + ['', _block('the topics'), ''] + _code_dtm_columns(min_freq, max_terms) + [
            f'Xw = weigh(X[:, cols], {_py(weighting)})   # {WEIGHTINGS[weighting]}',
            f'docs, terms, s, total = lsa_svd(Xw, k={k}, centering={_py(centering)}, seed={seed})   # {CENTERING[centering]}',
            'load, scores, R = varimax_topics(docs, terms, s)']
    else:
        cls = 'NMF' if method == 'nmf' else 'LatentDirichletAllocation'
        code = head + [f'from sklearn.decomposition import {cls}'] + _code_dtm_columns(min_freq, max_terms) + [
            f'Xw = weigh(X[:, cols], {_py(weighting)})   # {WEIGHTINGS[weighting]}']
        if method == 'nmf':
            code += [f'model = NMF(n_components={k}, init="nndsvda", max_iter=500, random_state={seed})',
                     'scores = model.fit_transform(Xw)   # documents by topics',
                     'load = model.components_.T   # terms by topics',
                     'order = np.argsort(-(scores.sum(axis=0) * load.sum(axis=0)), kind="stable")   # the largest topic first']
        else:
            code += [f'model = LatentDirichletAllocation(n_components={k}, learning_method="batch", random_state={seed})',
                     'scores = model.fit_transform(Xw)   # each document\'s share of each topic',
                     'load = (model.components_ / model.components_.sum(axis=1, keepdims=True)).T   # each topic\'s term probabilities',
                     'order = np.argsort(-scores.sum(axis=0), kind="stable")   # the largest topic first']
        code += ['load, scores = load[:, order], scores[:, order]']
    fitted = code[len(head):]   # the lines from the document term matrix to the topics
    code += ['loadings = pd.DataFrame(load, index=chosen, columns=[f"Topic {t + 1}" for t in range(load.shape[1])])',
             f'for t in loadings: print(t, ", ".join(loadings[t].sort_values(ascending=False, kind="stable").index[:{top}]))']
    plot_code = {}
    if k >= 2:
        what = 'scores' if method == 'varimax' else ('share of the topic' if method == 'lda' else 'weight on the topic')
        plot_code['scores'] = '\n'.join(with_head(['import matplotlib.pyplot as plt']) + fitted + [
            'top3 = [", ".join(chosen[j] for j in np.argsort(-load[:, t], kind="stable")[:3]) for t in (0, 1)]   # each topic\'s three largest terms',
            f'size = {"6" if C.n_docs <= 2000 else "4"}',
            'fig, ax = plt.subplots(figsize=(4.4, 3.6), layout="constrained")',
            f'ax.scatter(scores[:, 0], scores[:, 1], s=(0.72 * size) ** 2, color="{BASE}", linewidths=0)   # each document\'s {what}',
            'ax.set_xlabel(f"Topic 1 ({top3[0]})")', 'ax.set_ylabel(f"Topic 2 ({top3[1]})")',
            f'ax.set_title({_py("Topic scores of " + column)})', 'plt.show()'])
    return {'column': column, 'method': method, 'plot_code': _dated(plot_code, table), 'k': k, 'n_docs': C.n_docs, 'weighting': weighting, 'centering': centering if method == 'varimax' else None,
            'min_freq': min_freq, 'max_terms': max_terms, 'seed': seed, 'terms': names, 'top': tops, 'loadings': load.T.tolist(),
            'variance': [{'topic': t + 1, 'variance': float(var[t]), 'percent': float(pct[t]), 'cum': float(np.sum(pct[:t + 1]))} for t in range(k)],
            'scores': T['scores'][:, :ns].T.tolist(), 'doc_rows': [[int(C.rows[i]) for i in d] for d in C.docs],
            'doc_labels': C.labels if id_col else None, 'code': '\n'.join(code)}


@api('text.dtm', packages=SK)
def dtm(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=1000, min_chars=1, max_chars=100,
        stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), weighting='binary',
        min_freq=1, max_terms=100, terms=None, where=None, table_name='data'):
    """Save Document Term Matrix: one column per term (the given terms, or
    the most frequent), each row the value of its document."""
    try:
        cfg = _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases)
        min_freq, max_terms = _dtm_spec(weighting, min_freq, max_terms)
        C = _corpus(table, column, rows, id_col, cfg)
    except ValueError as e:
        return {'error': str(e)}
    cols = _chosen(C, min_freq, max_terms, terms)
    if not cols:
        return {'error': 'no terms to save'}
    Xw = weigh(C.X[:, cols], weighting).toarray()
    row_doc = np.empty(len(C.rows), dtype=int)
    for d, members in enumerate(C.docs):
        row_doc[members] = d
    code = _code_head(table, table_name, column, rows, id_col, cfg, where=where) + ['', _block('the document term matrix'), ''] + _code_dtm_columns(min_freq, max_terms, terms) + [
        f'dtm = pd.DataFrame(weigh(X[:, cols], {_py(weighting)}).toarray(), columns=chosen)   # {WEIGHTINGS[weighting]}; a document per line',
        'print(dtm.head(10))']
    return {'column': column, 'weighting': weighting, 'terms': [str(C.vocab[j]) for j in cols], 'rows': [int(r) for r in C.rows],
            'values': Xw[row_doc].T.tolist(), 'code': '\n'.join(code)}


@api('text.vectors', packages=SK)
def vectors(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=1000, min_chars=1, max_chars=100,
            stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), kind='svd', method='varimax',
            weighting='tfidf', centering='centered', min_freq=4, max_terms=1000, k=100, n_topics=10, seed=0, count=10, where=None, table_name='data'):
    """Save Document Singular Vectors (kind 'svd') or Save Topic Scores
    (kind 'topics'): the first `count` of them for every row, each row the
    value of its document."""
    if kind == 'svd':
        r = lsa(table, column, rows, id_col, language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add,
                recodes, phrases, weighting, centering, min_freq, max_terms, k, seed, show=count, where=where, table_name=table_name)
        vals = r.get('docs')
    else:
        r = topics(table, column, rows, id_col, language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add,
                   recodes, phrases, method, n_topics, weighting, centering, min_freq, max_terms, seed, scores=count, where=where, table_name=table_name)
        vals = r.get('scores')
    if 'error' in r:
        return r
    out_rows, values = [], [[] for _ in vals]
    for d, members in enumerate(r['doc_rows']):
        for row in members:
            out_rows.append(row)
            for c, v in enumerate(vals):
                values[c].append(v[d])
    return {'kind': kind, 'rows': out_rows, 'values': values, 'k': r['k'], 'code': r['code']}
