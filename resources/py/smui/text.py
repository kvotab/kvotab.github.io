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
             user's), stemmed by Snowball's English (Porter2) stemmer, JMP's
             (or Porter's 1980 algorithm; both written here from their
             published definitions) and recoded; a stemmed term ends in a dot (·)
  DTM        scikit-learn's CountVectorizer over the terms of each document
             (a row, or the rows that share an ID), weighted as JMP weights
             it: Binary, Ternary, Frequency, Log Freq, TF IDF (both logs
             base 10, as JMP's help writes them)
  LSA        the truncated SVD of the weighted matrix: TruncatedSVD when it
             is not centered, PCA (the same SVD of the centered matrix,
             without making the sparse matrix dense) when it is
  topics     the SVD's term coordinates rotated by varimax (Kaiser 1958),
             as JMP's Topic Analysis; or scikit-learn's NMF or
             LatentDirichletAllocation
  LCA        Latent Class Analysis: a Bernoulli mixture of the binary
             matrix fitted by EM (written here, sparse), JMP's top-term
             scores, and the clusters mapped by classical scaling of their
             Kullback-Leibler distances
  clusters   Cluster Terms and Cluster Documents: Ward's hierarchical
             clustering (scipy) of the SVD's term or document coordinates
  selection  Term Selection: an elastic net of a response on the matrix
             (scikit-learn's ElasticNet; glmnet's Newton steps for a binary
             response), chosen by AICc with JMP's early stopping
  sentiment  VADER (the vaderSentiment package, MIT), which the page fetches
             from PyPI the first time (its one wheel, pinned by sha256) and
             installs with micropip: its lexicon is never part of this site

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
from .util import one_line
from .registry import api

SK = predictive.SK
BASE, BAR = '#2f6690', '#8fa9c2'   # the points' and the bars' colours, light theme
STEMMING = ('none', 'combine', 'all')
STEMMERS = {'snowball': 'Snowball (Porter2)', 'porter': 'Porter (1980)'}
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


def read_terms(texts, stop_words, tokenizing='regex', regex=None, min_chars=1, max_chars=50,
               stemming='none', phrases=(), recodes=None, user_stop=(), stemmer='snowball'):
    """The tokens and the terms of each text, as Text Explorer reads them.

    tokens: the lowercase words of each text between min_chars and
    max_chars characters long (Regex: the built-in patterns, or regex;
    Basic Words: runs of letters and digits). terms: the tokens with the
    added phrases joined into one term each, less the stop words, stemmed
    by Snowball's English stemmer (Porter2; stemmer 'porter': Porter's
    1980 algorithm) ('combine': the words that share a stem with another
    word; 'all': every word of three or more letters a-z) and recoded
    ({term: new term}). Returns (tokens, terms, stem_of), stem_of the
    stemmed term of each word that has one."""
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
        stem = (SnowballStemmer if stemmer == 'snowball' else PorterStemmer)().stem
        words = {t for toks in joined for t in toks if t not in stop_words and t not in user_stop}
        stems = {w: stem(w) for w in words if len(w) > 2 and w.isascii() and w.isalpha()}
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
    frequent first, then the longer, then alphabetically (JMP's order), at
    most `most` of them."""
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
    kept = sorted((p for p, c in counts.items() if c > 1), key=lambda p: (-counts[p], -p.count(' '), p))   # JMP's order: count, longer, alphabetical
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


# >>> the Snowball stemmer
class SnowballStemmer:
    """The English stemmer of Snowball (Porter2), written here from its
    published definition (snowballstem.org, 'The English (Porter2)
    stemming algorithm') as Snowball 1 and 2 define it, with its exceptional
    forms. A word of one or two letters is left as it is."""

    VOWELS = frozenset('aeiouy')
    DOUBLES = ('bb', 'dd', 'ff', 'gg', 'mm', 'nn', 'pp', 'rr', 'tt')
    LI_ENDINGS = frozenset('cdeghkmnrt')
    PREFIXES = ('gener', 'commun', 'arsen')         # R1 starts after these
    EXCEPTIONS = {'skis': 'ski', 'skies': 'sky', 'dying': 'die', 'lying': 'lie', 'tying': 'tie', 'idly': 'idl', 'gently': 'gentl',
                  'ugly': 'ugli', 'early': 'earli', 'only': 'onli', 'singly': 'singl',
                  'sky': 'sky', 'news': 'news', 'howe': 'howe', 'atlas': 'atlas', 'cosmos': 'cosmos', 'bias': 'bias', 'andes': 'andes'}
    AFTER_1A = frozenset(('inning', 'outing', 'canning', 'herring', 'earring', 'proceed', 'exceed', 'succeed'))   # left as step 1a leaves them
    STEP1B = ('eedly', 'ingly', 'edly', 'eed', 'ing', 'ed')
    STEP2 = (('ational', 'ate'), ('tional', 'tion'), ('enci', 'ence'), ('anci', 'ance'), ('abli', 'able'), ('entli', 'ent'),
             ('ization', 'ize'), ('izer', 'ize'), ('ation', 'ate'), ('ator', 'ate'), ('alism', 'al'), ('aliti', 'al'), ('alli', 'al'),
             ('fulness', 'ful'), ('ousness', 'ous'), ('ousli', 'ous'), ('iveness', 'ive'), ('iviti', 'ive'), ('biliti', 'ble'),
             ('bli', 'ble'), ('ogi', 'og'), ('fulli', 'ful'), ('lessli', 'less'), ('li', ''))
    STEP3 = (('ational', 'ate'), ('tional', 'tion'), ('alize', 'al'), ('icate', 'ic'), ('iciti', 'ic'), ('ical', 'ic'), ('ful', ''),
             ('ness', ''), ('ative', ''))
    STEP4 = ('al', 'ance', 'ence', 'er', 'ic', 'able', 'ible', 'ant', 'ement', 'ment', 'ent', 'ism', 'ate', 'iti', 'ous', 'ive', 'ize', 'ion')

    def __init__(self):
        # the longest suffix of each step is the one that counts
        self.step2_rules = sorted(self.STEP2, key=lambda r: -len(r[0]))
        self.step3_rules = sorted(self.STEP3, key=lambda r: -len(r[0]))
        self.step4_rules = sorted(self.STEP4, key=len, reverse=True)
        self.memo = {}

    def _after_vc(self, w, start):
        """The position after the first non-vowel that follows a vowel, from start on (the end of w when there is none)."""
        n, i = len(w), start
        while i < n and w[i] not in self.VOWELS:
            i += 1
        while i < n and w[i] in self.VOWELS:
            i += 1
        return i + 1 if i < n else n

    def regions(self, w):
        """R1 and R2: where they start (len(w) when they are empty)."""
        p1 = next((len(p) for p in self.PREFIXES if w.startswith(p)), None)
        if p1 is None:
            p1 = self._after_vc(w, 0)
        return p1, (self._after_vc(w, p1) if p1 < len(w) else len(w))

    def short_syllable(self, s):
        """s ends in a short syllable: a vowel between non-vowels (the last not w, x or Y), or a vowel and a non-vowel at the start."""
        v = self.VOWELS
        if len(s) >= 3 and s[-1] not in v and s[-1] not in 'wxY' and s[-2] in v and s[-3] not in v:
            return True
        return len(s) == 2 and s[0] in v and s[1] not in v

    def stem(self, word):
        """The stem of a lowercase word (a word with letters other than
        a-z is stemmed too; Text Explorer gives it only words of a-z)."""
        s = self.memo.get(word)
        if s is None:
            s = self.memo[word] = self._stem(word)
        return s

    def _stem(self, w):
        if w in self.EXCEPTIONS:
            return self.EXCEPTIONS[w]
        if len(w) < 3:
            return w
        V = self.VOWELS
        if w.startswith("'"):
            w = w[1:]
        # a y at the start or after a vowel is a consonant: Y
        c = list(w)
        for i, ch in enumerate(c):
            if ch == 'y' and (i == 0 or c[i - 1] in V):
                c[i] = 'Y'
        w = ''.join(c)
        p1, p2 = self.regions(w)
        # step 0: an apostrophe ending
        for suf in ("'s'", "'s", "'"):
            if w.endswith(suf):
                w = w[:-len(suf)]
                break
        # step 1a: plurals
        if w.endswith('sses'):
            w = w[:-2]
        elif w.endswith(('ied', 'ies')):
            w = w[:-3] + ('i' if len(w) > 4 else 'ie')
        elif w.endswith(('us', 'ss')):
            pass
        elif w.endswith('s') and any(ch in V for ch in w[:-2]):
            w = w[:-1]
        if w in self.AFTER_1A:
            return w.replace('Y', 'y')
        # step 1b: -eed, -ed, -ing and their -ly forms
        for suf in self.STEP1B:
            if w.endswith(suf):
                if suf in ('eed', 'eedly'):
                    if len(w) - len(suf) >= p1:
                        w = w[:-len(suf)] + 'ee'
                elif any(ch in V for ch in w[:-len(suf)]):
                    w = w[:-len(suf)]
                    if w.endswith(('at', 'bl', 'iz')):
                        w += 'e'
                    elif w.endswith(self.DOUBLES):
                        w = w[:-1]
                    elif p1 >= len(w) and self.short_syllable(w):
                        w += 'e'
                break
        # step 1c: a final y after a non-vowel (not the first letter)
        if len(w) > 2 and w[-1] in 'yY' and w[-2] not in V:
            w = w[:-1] + 'i'
        # step 2, in R1
        for suf, new in self.step2_rules:
            if w.endswith(suf):
                if len(w) - len(suf) >= p1:
                    head = w[:-len(suf)]
                    if suf == 'ogi':
                        if head.endswith('l'):
                            w = head + new
                    elif suf == 'li':
                        if head and head[-1] in self.LI_ENDINGS:
                            w = head
                    else:
                        w = head + new
                break
        # step 3, in R1 (-ative in R2)
        for suf, new in self.step3_rules:
            if w.endswith(suf):
                k = len(w) - len(suf)
                if k >= p1 and (suf != 'ative' or k >= p2):
                    w = w[:k] + new
                break
        # step 4, in R2
        for suf in self.step4_rules:
            if w.endswith(suf):
                k = len(w) - len(suf)
                if k >= p2 and (suf != 'ion' or w[:k].endswith(('s', 't'))):
                    w = w[:k]
                break
        # step 5: a final e, a final double l
        if w.endswith('e'):
            k = len(w) - 1
            if k >= p2 or (k >= p1 and not self.short_syllable(w[:-1])):
                w = w[:-1]
        elif w.endswith('ll') and len(w) - 1 >= p2:
            w = w[:-1]
        return w.replace('Y', 'y')
# <<< the Snowball stemmer


# >>> the document term matrix
def weigh(X, weighting):
    """JMP's weightings of a document term matrix of counts X (scipy
    sparse, documents by terms), as JMP's help (Text Explorer, Save
    Options) gives them: Binary 1 when the term is in the document;
    Ternary 2 when it is there more than once, 1 once; Frequency its count;
    Log Freq log10(1 + count); TF IDF count * log10(documents / documents
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
        X = sp.csr_matrix(X @ sp.diags(np.log10(X.shape[0] / np.maximum(with_term, 1))))
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


# >>> latent class analysis
def lca_em(X, k, seed=0, n_init=5, max_iter=1000, tol=1e-10, prior=0.01, progress=None):
    """Latent class analysis of a binary document term matrix X (scipy
    sparse, documents by terms, 0 or 1): a mixture of k classes in which a
    document of class c holds term t with probability P[t, c], each term
    independently (a Bernoulli mixture), fitted by EM (Dempster, Laird and
    Rubin 1977) from n_init random starts drawn from seed; the start with
    the best objective is kept. Each class's term probabilities have a
    Beta(1 + prior, 1 + prior) prior (so none is 0 or 1): the M step is
    P = (X' R + prior) / (N_c + 2 prior). A document's log-likelihood in
    class c is sum_t log(1 - P[t, c]) + x . logit(P[:, c]), one sparse
    product, so the matrix stays sparse. Returns (pi, P, R, loglik,
    iterations): the mixing probabilities, the term probabilities (terms by
    classes), each document's class probabilities, the log-likelihood and
    the iterations of the kept start; the classes largest first."""
    import scipy.sparse as sp
    from scipy.special import logsumexp
    X = sp.csr_matrix(X, dtype=float)
    X.data[:] = 1.0
    n, m = X.shape
    rng = np.random.default_rng(seed)
    best = None
    for start in range(n_init):
        R = rng.dirichlet(np.ones(k), size=n)
        old = -np.inf
        for it in range(1, max_iter + 1):
            Nc = R.sum(axis=0)
            pi = np.maximum(Nc, 1e-300) / n
            P = (np.asarray(X.T @ R) + prior) / (Nc + 2 * prior)
            lq = np.log1p(-P)
            L = np.log(pi) + lq.sum(axis=0) + np.asarray(X @ (np.log(P) - lq))
            ll = logsumexp(L, axis=1)
            R = np.exp(L - ll[:, None])
            obj = float(ll.sum() + prior * np.sum(np.log(P) + lq))   # the log-likelihood and the log prior
            if obj - old <= tol * abs(obj):
                break
            old = obj
        if best is None or obj > best[0]:
            best = (obj, pi, P, R, float(ll.sum()), it)
        if progress:
            progress(start + 1, n_init)
    _, pi, P, R, ll, it = best
    order = np.argsort(-pi, kind='stable')
    return pi[order], P[:, order], R[:, order], ll, it


def lca_summary(pi, P, n_docs, top=10):
    """What JMP's Latent Class Analysis reports of a fit: the BIC; for each
    term the cluster where it occurs at the highest rate (Most
    Characteristic) and the cluster a document holding it most likely comes
    from (Most Probable: the largest pi_c P[t, c]); each term's score in
    each cluster, 100 mean(p_t) log10(P[t, c] / mean(p_t)) with mean(p_t)
    the mean of the term's probabilities over the clusters (the top terms
    of a cluster score highest); and a map of the clusters: classical
    (Torgerson) multidimensional scaling of the symmetric Kullback-Leibler
    distances between the clusters' term distributions (each cluster's
    term probabilities scaled to sum to 1), D = sum_t (q_a - q_b) log(q_a
    / q_b) (Bigi 2003)."""
    m, k = P.shape
    params = (k - 1) + k * m
    mean = P.mean(axis=1, keepdims=True)
    score = 100 * mean * np.log10(P / mean)
    top_terms = [np.argsort(-score[:, c], kind='stable')[:top] for c in range(k)]
    q = P / P.sum(axis=0, keepdims=True)
    lq = np.log(q)
    D = np.zeros((k, k))
    for a in range(k):
        for b in range(a + 1, k):
            D[a, b] = D[b, a] = float(np.sum((q[:, a] - q[:, b]) * (lq[:, a] - lq[:, b])))
    J = np.eye(k) - 1.0 / k
    B = -0.5 * J @ (D ** 2) @ J
    ev, V = np.linalg.eigh(B)
    o = np.argsort(ev)[::-1]
    ev, V = ev[o], V[:, o]
    coords = np.zeros((k, 2))
    for j in range(min(2, k)):
        if ev[j] > 1e-12 * max(1.0, abs(ev[0])):
            v = V[:, j] * (1.0 if V[np.abs(V[:, j]).argmax(), j] >= 0 else -1.0)   # the largest coordinate positive
            coords[:, j] = v * np.sqrt(ev[j])
    return {'params': params, 'score': score, 'top': top_terms, 'characteristic': P.argmax(axis=1),
            'probable': (P * pi).argmax(axis=1), 'kl': D, 'coords': coords, 'eigenvalues': ev}
# <<< latent class analysis


# >>> term selection
def enet_select(X, y, family, alpha=0.99, n_grid=150, ratio=1e-4, early=True, seed=0):
    """Term selection as JMP's Term Selection runs Generalized Regression:
    an elastic net (alpha the lasso's share of the penalty, JMP's 0.99) of
    y on the columns of X (scipy sparse), each scaled by its standard
    deviation, with an unpenalized intercept, along n_grid penalties from
    the smallest that leaves every term out down to ratio times it. It
    minimizes -loglik/N + lambda (alpha |b|_1 + (1 - alpha) |b|^2 / 2):
    for 'normal' scikit-learn's ElasticNet (coordinate descent) as it is;
    for 'binomial' (y 0/1) as glmnet does (Friedman, Hastie and Tibshirani
    2010), Newton steps of weighted least squares, each an ElasticNet with
    the weights p(1 - p), warm started along the path. The fit with the
    smallest AICc (-2 log L + 2k + 2k(k + 1)/(N - k - 1), k the nonzero
    terms and the intercept, and the variance for the normal) is kept; with
    early stopping the path ends once 10 penalties in a row fail to improve
    it, not before four terms are in. Returns the path (each penalty's AICc
    and terms), the chosen step, the coefficients on the columns' own scale
    and the intercept."""
    import scipy.sparse as sp
    import warnings
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import ElasticNet
    X = sp.csr_matrix(X, dtype=float)
    y = np.asarray(y, dtype=float)
    N, m = X.shape
    mean = np.asarray(X.mean(axis=0)).ravel()
    sd = np.sqrt(np.maximum(np.asarray(X.multiply(X).mean(axis=0)).ravel() - mean ** 2, 0) * N / max(N - 1, 1))
    sd = np.where(sd > 0, sd, 1.0)
    Xs = sp.csr_matrix(X @ sp.diags(1.0 / sd))
    lam_max = float(np.max(np.abs(Xs.T @ (y - y.mean())))) / (N * alpha)
    lams = lam_max * np.logspace(0, np.log10(ratio), n_grid)
    dense = m <= 400   # up to 400 terms: a dense matrix and its Gram matrix, far quicker than the sparse sweeps
    if dense:
        Xs = Xs.toarray()
    model = ElasticNet(l1_ratio=alpha, tol=1e-7, max_iter=20000, warm_start=True, selection='cyclic', precompute=dense)
    b, b0 = np.zeros(m), (float(np.log(y.mean() / (1 - y.mean()))) if family == 'binomial' else float(y.mean()))
    path, best, since = [], None, 0
    for l, lam in enumerate(lams):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ConvergenceWarning)
            if family == 'normal':
                model.set_params(alpha=lam)
                model.fit(Xs, y)
                b, b0 = model.coef_.copy(), float(model.intercept_)
            else:
                for _ in range(50):   # Newton steps: a weighted elastic net of the working response
                    eta = np.asarray(Xs @ b).ravel() + b0
                    pr = np.clip(1 / (1 + np.exp(-eta)), 1e-5, 1 - 1e-5)
                    w = pr * (1 - pr)
                    z = eta + (y - pr) / w
                    model.set_params(alpha=lam * N / w.sum())   # ElasticNet divides the weighted squares by the sum of the weights
                    model.fit(Xs, z, sample_weight=w)
                    nb, nb0 = model.coef_.copy(), float(model.intercept_)
                    done = max(np.max(np.abs(nb - b)) if m else 0.0, abs(nb0 - b0)) < 1e-7
                    b, b0 = nb, nb0
                    if done:
                        break
        eta = np.asarray(Xs @ b).ravel() + b0
        if family == 'binomial':
            ll = float(np.sum(y * eta - np.logaddexp(0, eta)))
            kpar = int(np.sum(b != 0)) + 1
        else:
            rss = float(np.sum((y - eta) ** 2))
            ll = -0.5 * N * (np.log(2 * np.pi * rss / N) + 1) if rss > 0 else np.inf
            kpar = int(np.sum(b != 0)) + 2
        aicc = -2 * ll + 2 * kpar + (2 * kpar * (kpar + 1) / (N - kpar - 1) if N - kpar - 1 > 0 else np.inf)
        path.append({'lambda': float(lam), 'aicc': aicc, 'nonzero': int(np.sum(b != 0)), 'b': b / sd, 'b0': b0})
        if best is None or aicc < path[best]['aicc']:
            best, since = l, 0
        else:
            since += 1
        if early and since >= 10 and path[-1]['nonzero'] >= 4:
            break
    return {'path': path, 'best': best, 'coef': path[best]['b'], 'intercept': path[best]['b0'], 'lambda': path[best]['lambda'],
            'aicc': path[best]['aicc'], 'sd': sd, 'lam_max': lam_max}


def enet_wald(X, y, family, fit, alpha=0.99):
    """Wald tests of the kept terms of enet_select's fit: each estimate
    over its standard error from the Hessian of the penalized likelihood on
    the kept terms and the intercept, X'WX + N lambda (1 - alpha) (the
    ridge part; W the binomial weights p(1 - p), or 1 and the variance
    RSS / (N - k) for the normal), inverted by a pseudo-inverse. They do
    not allow for the selection. Returns (the kept columns, their
    p-values)."""
    import scipy.sparse as sp
    from scipy.stats import norm
    X = sp.csr_matrix(X, dtype=float)
    y = np.asarray(y, dtype=float)
    N = X.shape[0]
    b, b0, lam = fit['coef'], fit['intercept'], fit['lambda']
    kept = np.flatnonzero(b)
    if not len(kept):
        return kept, np.array([])
    A = np.column_stack([np.ones(N), X[:, kept].toarray()])
    eta = A @ np.r_[b0, b[kept]]
    ridge = N * lam * (1 - alpha) * np.diag(np.r_[0.0, 1.0 / fit['sd'][kept] ** 2])   # the ridge on the scaled terms, in their own units
    if family == 'binomial':
        pr = 1 / (1 + np.exp(-eta))
        cov = np.linalg.pinv(A.T @ (A * (pr * (1 - pr))[:, None]) + ridge)
    else:
        s2 = float(np.sum((y - eta) ** 2)) / max(N - len(kept) - 1, 1)
        cov = s2 * np.linalg.pinv(A.T @ A + ridge)
    se = np.sqrt(np.maximum(np.diag(cov)[1:], 0))
    z = np.where(se > 0, b[kept] / np.where(se > 0, se, 1.0), np.inf)
    return kept, 2 * norm.sf(np.abs(z))
# <<< term selection


# >>> the clusters of the singular vectors
def ward(V):
    """Ward's hierarchical clustering of the rows of V (scipy's linkage),
    each join's distance as JMP's Hierarchical Cluster gives it: the
    increase in the within-cluster sum of squares. Returns the joins
    (scipy's linkage matrix) and the leaves in the order of the dendrogram."""
    from scipy.cluster.hierarchy import leaves_list, linkage
    Z = linkage(np.asarray(V, dtype=float), 'ward')
    Z[:, 2] = Z[:, 2] ** 2 / 2
    return Z, leaves_list(Z)


def clusters_at(Z, k):
    """The k clusters of a tree: each leaf's cluster (0 to k - 1), numbered
    in the order of the dendrogram's leaves, after the first n - k joins."""
    from scipy.cluster.hierarchy import leaves_list
    n = Z.shape[0] + 1
    parent = np.full(2 * n - 1, -1)
    for s, (a, b) in enumerate(Z[:, :2].astype(int)):
        parent[a] = parent[b] = n + s
    root = np.arange(2 * n - 1)
    for v in range(2 * n - k - 1, -1, -1):
        if 0 <= parent[v] < 2 * n - k:
            root[v] = root[parent[v]]
    number = {}
    for leaf in leaves_list(Z):
        number.setdefault(root[leaf], len(number))
    return np.array([number[root[i]] for i in range(n)])


def default_clusters(heights, n):
    """Where the joining distance jumps most: the largest ratio of a join to
    the one before, from 2 to 10 clusters (as Hierarchical Cluster's default)."""
    k, ratio = min(3, n), -np.inf
    for q in range(2, min(10, n - 1) + 1):
        up, down = heights[n - q], heights[n - q - 1]
        r = up / down if down > 0 else (np.inf if up > 0 else 0)
        if r > ratio:
            k, ratio = q, r
    return k
# <<< the clusters of the singular vectors


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


# The reading options every entry point takes, with JMP's launch defaults
# (its help's launch window, JMP 14 to 19): 4 words per phrase, 5000 phrases,
# words of 1 to 50 characters, no stemming, the Regex tokenizer.
READ_DEFAULTS = {'language': 'english', 'max_words': 4, 'max_phrases': 5000, 'min_chars': 1, 'max_chars': 50, 'stemming': 'none',
                 'tokenizing': 'regex', 'regex': None, 'stop_add': (), 'recodes': None, 'phrases': (), 'stemmer': 'snowball'}


def _config(language='english', max_words=4, max_phrases=5000, min_chars=1, max_chars=50, stemming='none',
            tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), stemmer='snowball'):
    if str(language or 'english').lower() != 'english':
        raise ValueError('Text Explorer reads English here (its stop words and its stemmer are English)')
    cfg = {
        'max_words': _int(max_words, 'Maximum Words per Phrase', 1, MAX_PHRASE_WORDS),
        'max_phrases': _int(max_phrases, 'Maximum Number of Phrases', 0, 100000),
        'min_chars': _int(min_chars, 'Minimum Characters per Word', 1, 1000),
        'max_chars': _int(max_chars, 'Maximum Characters per Word', 1, 100000),
        'stemming': stemming if stemming in STEMMING else None,
        'stemmer': (stemmer or 'snowball') if (stemmer or 'snowball') in STEMMERS else None,
        'tokenizing': tokenizing if tokenizing in TOKENIZING else None,
        'regex': (regex or '').strip() or None,
    }
    if cfg['stemming'] is None:
        raise ValueError(f'Stemming is one of {", ".join(STEMMING)}, not {stemming!r}')
    if cfg['stemmer'] is None:
        raise ValueError(f'the stemmer is snowball or porter, not {stemmer!r}')
    if cfg['stemming'] == 'none':
        cfg['stemmer'] = 'snowball'   # no stemming: the choice of stemmer changes nothing (nor the cache)
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
            'stemming': cfg['stemming'], 'phrases': cfg['phrases'], 'recodes': cfg['recodes'], 'user_stop': cfg['stop_add'],
            'stemmer': cfg['stemmer']}


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
    shown = (lambda k: data.level_label(table, id_col, k, default=predictive.level_label(k))) if hasattr(data, 'level_label') else predictive.level_label
    for i, k in enumerate(keys):
        if k not in pos:
            pos[k] = len(docs)
            docs.append([])
            labels.append(shown(k))   # the ID's Value Label, when it has one
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
        L.append(f'df = df[{test}]   # only the rows where {one_line(w["column"])} is {one_line(shown)}')
    if rows is not None and n:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.flatnonzero(match & ~keep).tolist()
        if drop and not where and keep.sum() <= n / 2:
            return [f'df = df.loc[{np.flatnonzero(keep).tolist()}]   # the rows of the report']
        if drop:
            L.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
    return L


def _code_read(table, table_name, column, rows, id_col, imports, where=None, keep_every=False):
    """Read the exported table (the text, the ID and a character By column
    as text), keep the report's rows and, with an ID, the rows that have one."""
    dtypes = {column: 'str'}
    if id_col:
        dtypes[id_col] = 'str'
    for w in where or []:
        if data.meta(table, w['column']).get('dataType') != 'numeric':
            dtypes[w['column']] = 'str'
    L = [*imports, '',
         f'df = pd.read_csv({_py(table_name + ".csv")}, dtype={_py(dtypes)}, keep_default_na=False)   # the table as File > Export CSV writes it; the text as it is']
    L += _keep_lines(table, rows, where)
    if id_col:
        if keep_every:
            L.append('every = df   # the report\'s rows, with an ID or without')
        L.append(f'df = df[df[{_py(id_col)}] != ""]   # the rows with an ID')
    return L


def _code_head(table, table_name, column, rows, id_col, cfg, extra_imports=(), where=None, keep_every=False):
    """Read the exported table, keep the report's rows, and read the texts
    as the report does: the lines up to the terms of every document.
    keep_every: with an ID, keep the report's rows before the rows without
    one are left out (as every), for the word cloud's By Column colouring."""
    L = _code_read(table, table_name, column, rows, id_col, ['import re', 'import numpy as np', 'import pandas as pd',
                   'from sklearn.feature_extraction.text import CountVectorizer, ENGLISH_STOP_WORDS', *extra_imports], where, keep_every)
    L += ['', _block('reading the texts'), '']
    if cfg['stemming'] != 'none':
        L += [_block('the Snowball stemmer' if cfg['stemmer'] == 'snowball' else 'the Porter stemmer'), '']
    args = [f'tokenizing={_py(cfg["tokenizing"])}']
    if cfg['regex']:
        args.append(f'regex={_py(cfg["regex"])}')
    args += [f'min_chars={cfg["min_chars"]}', f'max_chars={cfg["max_chars"]}', f'stemming={_py(cfg["stemming"])}']
    if cfg['stemming'] != 'none':
        args.append(f'stemmer={_py(cfg["stemmer"])}')
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

def _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases, stemmer='snowball'):
    return _config(language=language, max_words=max_words, max_phrases=max_phrases, min_chars=min_chars, max_chars=max_chars,
                   stemming=stemming, tokenizing=tokenizing, regex=regex, stop_add=stop_add, recodes=recodes, phrases=phrases, stemmer=stemmer)


def _read(opts):
    """The reading options among an entry point's keyword arguments (the
    page sends them to every call), checked: _config's dict."""
    return _config(**{k: opts[k] for k in READ_DEFAULTS if k in opts})


@api('text.explore', packages=SK)
def explore(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=5000, min_chars=1, max_chars=50,
            stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), where=None, table_name='data',
            stemmer='snowball'):
    """Summary Counts, the Term List and the Phrase List of a column, with
    the rows that hold each term and phrase (for linking), the stems, and
    the stop words; the code, and the lines the word cloud's code starts
    with (cloud_head: the page adds its layout)."""
    try:
        cfg = _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases, stemmer)
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
def lsa(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=5000, min_chars=1, max_chars=50,
        stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), weighting='tfidf',
        centering='scaled', min_freq=4, max_terms=1000, k=100, seed=0, show=2, where=None, table_name='data', stemmer='snowball'):
    """Latent Semantic Analysis: the singular values, and the first `show`
    coordinates of every document and of every term of the matrix; the code,
    the singular values' bar chart's (plot_code) and the lines the SVD
    plots' code starts with (svd_head: the page adds the drawing)."""
    try:
        cfg = _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases, stemmer)
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
    # the eigenvalues of the equivalent principal components: of the covariance (Centered) or the correlation
    # (Centered and Scaled) matrix, s^2 / (n - 1); of X'X / n uncentered (JMP divides by nDoc then)
    eig = s ** 2 / (C.n_docs if centering == 'uncentered' else C.n_docs - 1)
    singular = [{'number': i + 1, 'value': float(s[i]), 'eigen': float(eig[i]), 'percent': float(pct[i]), 'cum': float(np.sum(pct[:i + 1]))} for i in range(k)]
    doc_rows = [[int(C.rows[i]) for i in d] for d in C.docs]
    code = _lsa_code(table, table_name, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, k, seed, where) + [
        'pct = 100 * s ** 2 / total   # the share of the matrix\'s sum of squares',
        f'eigen = s ** 2 / {"Xw.shape[0]" if centering == "uncentered" else "(Xw.shape[0] - 1)"}   # the equivalent principal components\' eigenvalues',
        'singular_values = pd.DataFrame({"Number": np.arange(1, len(s) + 1), "Singular Value": s, "Eigenvalue": eigen, "Percent": pct, "Cum Percent": np.cumsum(pct)})',
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
def topics(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=5000, min_chars=1, max_chars=50,
           stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), method='varimax',
           n_topics=10, weighting='tfidf', centering='scaled', min_freq=4, max_terms=1000, seed=0, top=10, scores=2,
           where=None, table_name='data', stemmer='snowball'):
    """Topic Analysis: varimax-rotated SVD (JMP's), or NMF or LDA. The top
    terms of each topic, every term's loadings, the variance of each topic
    and the first `scores` topic scores of every document."""
    try:
        cfg = _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases, stemmer)
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
def dtm(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=5000, min_chars=1, max_chars=50,
        stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), weighting='binary',
        min_freq=1, max_terms=100, terms=None, where=None, table_name='data', stemmer='snowball'):
    """Save Document Term Matrix: one column per term (the given terms, or
    the most frequent), each row the value of its document."""
    try:
        cfg = _parse_args(language, max_words, max_phrases, min_chars, max_chars, stemming, tokenizing, regex, stop_add, recodes, phrases, stemmer)
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
def vectors(table, column, rows=None, id_col=None, language='english', max_words=4, max_phrases=5000, min_chars=1, max_chars=50,
            stemming='none', tokenizing='regex', regex=None, stop_add=(), recodes=None, phrases=(), kind='svd', method='varimax',
            weighting='tfidf', centering='scaled', min_freq=4, max_terms=1000, k=100, n_topics=10, seed=0, count=10, where=None, table_name='data',
            stemmer='snowball'):
    """Save Document Singular Vectors (kind 'svd') or Save Topic Scores
    (kind 'topics'): the first `count` of them for every row, each row the
    value of its document."""
    read = dict(language=language, max_words=max_words, max_phrases=max_phrases, min_chars=min_chars, max_chars=max_chars, stemming=stemming,
                tokenizing=tokenizing, regex=regex, stop_add=stop_add, recodes=recodes, phrases=phrases, stemmer=stemmer)
    if kind == 'svd':
        r = lsa(table, column, rows, id_col, weighting=weighting, centering=centering, min_freq=min_freq, max_terms=max_terms, k=k, seed=seed,
                show=count, where=where, table_name=table_name, **read)
        vals = r.get('docs')
    else:
        r = topics(table, column, rows, id_col, method=method, n_topics=n_topics, weighting=weighting, centering=centering, min_freq=min_freq,
                   max_terms=max_terms, seed=seed, scores=count, where=where, table_name=table_name, **read)
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


# ---------------------------------------------------------------------------
# Latent Class Analysis, the clusters of the singular vectors
# ---------------------------------------------------------------------------

def _row_values(C, per_doc):
    """Each row's value of its document: (the rows, the values)."""
    rows, vals = [], []
    for d, members in enumerate(C.docs):
        for i in members:
            rows.append(int(C.rows[i]))
            vals.append(per_doc[d])
    return rows, vals


LCA_STARTS = 5


@api('text.lca', packages=SK)
def lca(table, column, rows=None, id_col=None, n_clusters=5, min_freq=4, max_terms=1000, seed=0, where=None, table_name='data', **read):
    """Latent Class Analysis of the binary document term matrix: the
    mixture probabilities, the term probabilities by cluster, the top terms,
    each document's cluster probabilities, the BIC and the MDS map of the
    clusters; the code and the map's code."""
    try:
        cfg = _read(read)
        min_freq, max_terms = _dtm_spec('binary', min_freq, max_terms)
        k = _int(n_clusters, 'Number of Clusters', 2, 100)
        seed = int(predictive.seed_of(seed) or 0)
        C = _corpus(table, column, rows, id_col, cfg)
        cols = _chosen(C, min_freq, max_terms)
        if len(cols) < 2:
            raise ValueError(f'{len(cols)} term{"" if len(cols) == 1 else "s"} occur{"s" if len(cols) == 1 else ""} at least {min_freq} times: '
                             'Latent Class Analysis needs two or more')
        if C.n_docs <= k:
            raise ValueError(f'{C.n_docs} documents: {k} clusters need more')
    except ValueError as e:
        return {'error': str(e)}

    def build():
        Xb = weigh(C.X[:, cols], 'binary')
        pi, P, R, ll, it = lca_em(Xb, k, seed=seed, n_init=LCA_STARTS, progress=lambda d, t: print(f'smui:progress lca {d} {t}', flush=True))
        return {'pi': pi, 'P': P, 'R': R, 'll': ll, 'it': it, 'S': lca_summary(pi, P, C.n_docs)}
    spec = {'column': column, 'id': id_col, **cfg, 'min_freq': min_freq, 'max_terms': max_terms, 'k': k, 'seed': seed}
    F = predictive.cached('text.lca', table, rows, spec, build)
    pi, P, R, S = F['pi'], F['P'], F['R'], F['S']
    n = C.n_docs
    names = [str(C.vocab[j]) for j in cols]
    likely = R.argmax(axis=1)
    bic = -2 * F['ll'] + S['params'] * math.log(n)
    head = lambda extra=(): _code_head(table, table_name, column, rows, id_col, cfg, extra, where) + [   # noqa: E731
        '', _block('the document term matrix'), '', _block('latent class analysis'), ''] + _code_dtm_columns(min_freq, max_terms) + [
        'Xb = weigh(X[:, cols], "binary")   # Binary: 1 when the document holds the term',
        f'pi, P, R, loglik, iterations = lca_em(Xb, k={k}, seed={seed}, n_init={LCA_STARTS})   # {k} clusters, the best of {LCA_STARTS} random starts',
        'summary = lca_summary(pi, P, Xb.shape[0])']
    code = head() + [
        'bic = -2 * loglik + summary["params"] * np.log(Xb.shape[0])   # the parameters: k - 1 mixing probabilities and k per term',
        'print(f"BIC {bic:.6g}, log-likelihood {loglik:.6g}, {iterations} iterations")',
        'print(pd.DataFrame({"Cluster": np.arange(1, len(pi) + 1), "Probability": pi}).to_string(index=False))   # Cluster Mixture Probabilities',
        'term_probs = pd.DataFrame(P, index=chosen, columns=[f"Cluster {c + 1}" for c in range(len(pi))])   # Term Probabilities by Cluster',
        'term_probs["Cluster Most Characteristic"] = summary["characteristic"] + 1',
        'term_probs["Cluster Most Probable"] = summary["probable"] + 1',
        'print(term_probs.head(20))',
        'for c, top in enumerate(summary["top"]):',
        '    print(f"Cluster {c + 1}:", ", ".join(chosen[j] for j in top))   # Top Terms by Cluster',
        'most_likely = R.argmax(axis=1) + 1   # each document\'s Most Likely Cluster']
    mds = head(['import matplotlib.pyplot as plt']) + [
        'xy = summary["coords"]   # the clusters mapped: classical scaling of their Kullback-Leibler distances',
        'size = 10 + 30 * np.sqrt(pi / pi.max())   # each cluster\'s marker across, in pixels: its area follows its mixing probability',
        'fig, ax = plt.subplots(figsize=(4, 3.6), layout="constrained")',
        f'ax.axhline(0, color="#e0d7ce", linewidth=0.72, zorder=0)', f'ax.axvline(0, color="#e0d7ce", linewidth=0.72, zorder=0)',
        f'ax.scatter(xy[:, 0], xy[:, 1], s=(0.72 * size) ** 2, color="{BASE}", alpha=0.6, linewidths=0)',
        'for c in range(len(pi)):',
        '    ax.text(xy[c, 0], xy[c, 1], f"Cluster {c + 1}", ha="center", va="center", fontsize=7.56, color="#352921")',
        'ax.set_xlabel("MDS1")', 'ax.set_ylabel("MDS2")', 'ax.set_title("MDS Plot")', 'plt.show()']
    counts = np.bincount(likely, minlength=k)
    return {'column': column, 'k': k, 'n_docs': n, 'n_terms': len(cols), 'min_freq': min_freq, 'max_terms': max_terms, 'seed': seed, 'starts': LCA_STARTS,
            'loglik': F['ll'], 'bic': bic, 'params': S['params'], 'iterations': F['it'], 'pi': pi, 'docs_in': counts,
            'terms': names, 'term_counts': [int(C.counts[j]) for j in cols], 'P': P.T.tolist(),
            'characteristic': S['characteristic'] + 1, 'probable': S['probable'] + 1,
            'top': [[{'term': names[j], 'score': float(S['score'][j, c])} for j in S['top'][c]] for c in range(k)],
            'kl': S['kl'], 'coords': S['coords'], 'R': R.tolist(), 'likely': likely + 1,
            'doc_rows': [[int(C.rows[i]) for i in d] for d in C.docs], 'doc_labels': C.labels if id_col else None,
            'code': '\n'.join(code), 'plot_code': _dated({'mds': '\n'.join(mds)}, table)}


@api('text.lca_save', packages=SK)
def lca_save(table, column, rows=None, id_col=None, n_clusters=5, min_freq=4, max_terms=1000, seed=0, where=None, table_name='data', **read):
    """Save Probabilities and Save Cluster: each row its document's cluster
    probabilities and most likely cluster."""
    r = lca(table, column, rows, id_col, n_clusters, min_freq, max_terms, seed, where, table_name, **read)
    if 'error' in r:
        return r
    cfg = _read(read)
    C = _corpus(table, column, rows, id_col, cfg)
    R = np.asarray(r['R'])
    out_rows, likely = _row_values(C, [int(v) for v in r['likely']])
    probs = [_row_values(C, R[:, c].tolist())[1] for c in range(r['k'])]
    return {'rows': out_rows, 'likely': likely, 'probs': probs, 'k': r['k'], 'code': r['code']}


def _cluster_lines(kind, kk):
    what = 'terms' if kind == 'terms' else 'docs'
    return ['', _block('the clusters of the singular vectors'), '',
            f'V = {what}   # the {"terms" if kind == "terms" else "documents"}\' coordinates on the singular vectors ({"V S" if kind == "terms" else "U S"})',
            'Z, order = ward(V)   # Ward\'s method; each join at the increase in the within-cluster sum of squares',
            'heights, n = Z[:, 2], len(V)',
            f'k = {kk}   # Number of Clusters',
            'cluster = clusters_at(Z, k)   # each one\'s cluster, numbered in the order of the dendrogram (from 0)']


@api('text.cluster', packages=SK)
def cluster(table, column, rows=None, id_col=None, kind='terms', weighting='tfidf', centering='scaled', min_freq=4, max_terms=1000, k=100,
            seed=0, n_clusters=None, where=None, table_name='data', **read):
    """Cluster Terms (kind 'terms') or Cluster Documents ('docs'): Ward's
    hierarchical clustering of the terms' (V S) or the documents' (U S)
    coordinates on the singular vectors; the joins, the default and the
    chosen number of clusters and each one's cluster; the code and the
    dendrogram's code."""
    try:
        cfg = _read(read)
        if kind not in ('terms', 'docs'):
            raise ValueError(f'kind is terms or docs, not {kind!r}')
        min_freq, max_terms = _dtm_spec(weighting, min_freq, max_terms)
        if centering not in CENTERING:
            raise ValueError(f'the centering is one of {", ".join(CENTERING)}, not {centering!r}')
        k = _int(k, 'Number of Singular Vectors', 1, 100000)
        seed = int(predictive.seed_of(seed) or 0)
        C, S = _svd(table, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, k, seed)
        V = S['terms'] if kind == 'terms' else S['docs']
        n = V.shape[0]
        if kind == 'docs' and n > 4000:
            raise ValueError(f'{n} documents: Cluster Documents takes at most 4000 here (hierarchical clustering keeps all n(n - 1)/2 distances)')
        if n < 3:
            raise ValueError('fewer than three to cluster')
    except ValueError as e:
        return {'error': str(e)}
    spec = {'column': column, 'id': id_col, **cfg, 'weighting': weighting, 'centering': centering, 'min_freq': min_freq, 'max_terms': max_terms,
            'k': S['k'], 'seed': seed, 'kind': kind}
    Z, order = predictive.cached('text.ward', table, rows, spec, lambda: ward(V))
    heights = Z[:, 2]
    kdef = default_clusters(heights, n)
    kk = kdef if n_clusters in (None, '') else max(1, min(n, int(math.floor(float(n_clusters) + 0.5))))
    lab = clusters_at(Z, kk)
    if kind == 'terms':
        names = [str(C.vocab[j]) for j in S['cols']]
        row_sets = None
    else:
        names = list(C.labels) if id_col else [str(int(C.rows[d[0]]) + 1) for d in C.docs]   # an ID's label, or the row's number
        row_sets = [[int(C.rows[i]) for i in d] for d in C.docs]
    base = _lsa_code(table, table_name, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, S['k'], seed, where)
    code = base + _cluster_lines(kind, kk) + (
        ['print(pd.DataFrame({"Term": chosen, "Cluster": cluster + 1}).sort_values(["Cluster", "Term"]).to_string(index=False))'] if kind == 'terms' else
        ['print(pd.Series(cluster + 1).value_counts().sort_index())   # the documents in each cluster'])
    return {'kind': kind, 'n': n, 'k_vectors': S['k'], 'merges': Z[:, :2].astype(int), 'heights': heights, 'order': order, 'default_k': kdef, 'n_clusters': kk,
            'labels': lab, 'names': names, 'doc_rows': row_sets, 'weighting': weighting, 'centering': centering, 'code': '\n'.join(code),
            'dendro_head': _dated('\n'.join(_lsa_code(table, table_name, column, rows, id_col, cfg, weighting, centering, min_freq, max_terms, S['k'], seed, where,
                                                      ['import matplotlib.pyplot as plt']) + _cluster_lines(kind, kk)), table)}


# ---------------------------------------------------------------------------
# Term Selection (JMP Pro): an elastic net of a response on the document term matrix
# ---------------------------------------------------------------------------

def _doc_response(table, response, C):
    """Each document's response: the value of its first row that has one (None without)."""
    raw = data.raw(table, response)
    out = []
    for d in C.docs:
        v = None
        for i in d:
            x = raw[int(C.rows[i])]
            if x is None or (isinstance(x, float) and math.isnan(x)):
                continue
            v = x
            break
        out.append(v)
    return out


@api('text.termsel', packages=SK)
def termsel(table, column, response, rows=None, id_col=None, target=None, weighting='binary', min_freq=10, max_terms=1000, early=True,
            alpha=0.99, seed=0, where=None, table_name='data', **read):
    """Term Selection: the terms an elastic net of the response on the
    document term matrix keeps (JMP's defaults: Elastic Net, alpha 0.99,
    AICc, early stopping, terms seen 10 times or more), with their
    coefficients and LogWorths, and each document's positive and negative
    contributions and prediction; the code and the coefficients' bars'
    code."""
    try:
        cfg = _read(read)
        min_freq, max_terms = _dtm_spec(weighting, min_freq, max_terms)
        if not response:
            raise ValueError('choose a response column')
        if response in (column, id_col):
            raise ValueError('the response is the text column or the ID')
        a = float(alpha)
        if not 0 < a <= 1:
            raise ValueError('the Elastic Net Alpha is the lasso share of the penalty: above 0, at most 1')
        seed = int(predictive.seed_of(seed) or 0)
        m = data.meta(table, response)
        mt, numeric = m.get('modelingType'), m.get('dataType') == 'numeric'
        C = _corpus(table, column, rows, id_col, cfg)
        cols = _chosen(C, min_freq, max_terms)
        if len(cols) < 2:
            raise ValueError(f'{len(cols)} term{"" if len(cols) == 1 else "s"} occur{"s" if len(cols) == 1 else ""} at least {min_freq} times: '
                             'Term Selection needs two or more')
        yv = _doc_response(table, response, C)
        keep = [d for d, v in enumerate(yv) if v is not None]
        levels = None
        if mt == 'nominal' or (mt == 'ordinal' and not numeric):
            if mt == 'ordinal':
                raise ValueError(f'{response} is ordinal and character: JMP models an ordinal response by its numbers, so it must be numeric')
            levels = [predictive.level_label(v) for v in (m.get('levels') or sorted({v for v in yv if v is not None}))]
            tgt = predictive.level_label(target) if target not in (None, '') else levels[0]
            if tgt not in levels:
                raise ValueError(f'{tgt} is not a level of {response}')
            y = np.array([1.0 if predictive.level_label(yv[d]) == tgt else 0.0 for d in keep])
            family = 'binomial'
            if y.min() == y.max():
                raise ValueError(f'every document with a {response} is {"" if y[0] else "not "}{tgt}: nothing to explain')
        else:
            tgt = None
            y = np.array([float(yv[d]) for d in keep])
            family = 'normal'
        if len(keep) < 10:
            raise ValueError(f'{len(keep)} documents with a {response}: Term Selection needs ten or more')
    except ValueError as e:
        return {'error': str(e)}
    Xw = weigh(C.X[:, cols], weighting)[keep]
    spec = {'column': column, 'id': id_col, **cfg, 'response': response, 'target': tgt, 'weighting': weighting, 'min_freq': min_freq,
            'max_terms': max_terms, 'early': bool(early), 'alpha': a, 'seed': seed}
    F = predictive.cached('text.termsel', table, rows, spec, lambda: enet_select(Xw, y, family, alpha=a, early=bool(early), seed=seed))
    b, b0 = F['coef'], F['intercept']
    sel = np.flatnonzero(b != 0)
    names = [str(C.vocab[j]) for j in cols]
    # LogWorth: the Wald test of each kept term, the penalized likelihood's Hessian on the kept terms
    note = None
    _, pv = enet_wald(Xw, y, family, F, a)
    lw = [float(-math.log10(max(p, 1e-300))) for p in pv]
    eta = np.asarray(Xw @ b).ravel() + b0
    pos = np.asarray(Xw @ np.where(b > 0, b, 0.0)).ravel()
    neg = np.asarray(Xw @ np.where(b < 0, b, 0.0)).ravel()
    pred = 1 / (1 + np.exp(-eta)) if family == 'binomial' else eta
    terms_out = sorted(({'term': names[j], 'coef': float(b[j]), 'logworth': lw[k], 'count': int(C.counts[cols[j]]), 'cases': int(C.with_term[cols[j]])}
                        for k, j in enumerate(sel)), key=lambda r: -r['coef'])
    path = F['path']
    head = _code_head(table, table_name, column, rows, id_col, cfg, (), where) + [
        '', _block('the document term matrix'), '', _block('term selection'), ''] + _code_dtm_columns(min_freq, max_terms) + [
        f'Xw = weigh(X[:, cols], {_py(weighting)})   # {WEIGHTINGS[weighting]}; a document per line',
        f'resp = df[{_py(response)}]' + ('' if family == 'normal' and numeric else '.astype(str)'),
        ('first = resp.groupby(df[' + _py(id_col) + '], sort=False).apply(lambda s: s.dropna().iloc[0] if s.notna().any() else None)   # each document\'s response: its first row\'s'
         if id_col else 'first = resp.reset_index(drop=True)   # each document\'s response'),
        'keep = np.flatnonzero(first.notna().to_numpy())   # the documents with a response']
    if family == 'binomial':
        lvl_expr = 'first.iloc[keep].map(lambda v: v[:-2] if v.endswith(".0") else v)' if numeric else 'first.iloc[keep]'
        head += [f'y = ({lvl_expr} == {_py(tgt)}).to_numpy(float)   # the target level {tgt} against the rest']
    else:
        head += ['y = first.iloc[keep].to_numpy(float)']
    head += [f'fit = enet_select(Xw[keep], y, {_py(family)}, alpha={a!r}, early={bool(early)}, seed={seed})   # Elastic Net, AICc{", early stopping" if early else ""}',
             'b = fit["coef"]', 'kept = np.flatnonzero(b)']
    code = head + [
        f'kept, p = enet_wald(Xw[keep], y, {_py(family)}, fit, alpha={a!r})   # Wald p-values: the penalized likelihood\'s Hessian on the kept terms',
        'term_scores = pd.DataFrame({"Term": [chosen[j] for j in kept], "Coefficient": b[kept], "LogWorth": -np.log10(np.maximum(p, 1e-300))})',
        'term_scores = term_scores.sort_values("Coefficient", ascending=False, kind="stable")',
        'print(f"AICc {fit[\'aicc\']:.6g} at lambda {fit[\'lambda\']:.6g}; {len(kept)} terms")',
        'print(term_scores.to_string(index=False))']
    top = sorted(terms_out, key=lambda r: -abs(r['coef']))[:30]
    bars = None
    if top:
        bars = '\n'.join(_code_head(table, table_name, column, rows, id_col, cfg, ['import matplotlib.pyplot as plt'], where) + head[len(_code_head(table, table_name, column, rows, id_col, cfg, (), where)):] + [
            'top = kept[np.argsort(-np.abs(b[kept]), kind="stable")][:30][::-1]   # the 30 largest in size, the largest at the top',
            f'fig, ax = plt.subplots(figsize=(4.4, {max(160, 16 * len(top) + 60) / 100:g}), layout="constrained")',
            f'ax.barh(np.arange(len(top)), b[top], color=["{BASE}" if v > 0 else "#b0413e" for v in b[top]], height=0.75)',
            'ax.set_yticks(np.arange(len(top)), [chosen[j] for j in top])', 'ax.axvline(0, color="#352921", linewidth=0.72)',
            'ax.set_xlabel("Coefficient")', f'ax.set_title({_py("Term coefficients" + (f" ({response} = {tgt})" if tgt is not None else f" ({response})"))})', 'plt.show()'])
    doc_rows = [[int(C.rows[i]) for i in C.docs[d]] for d in keep]
    return {'column': column, 'response': response, 'family': family, 'target': tgt, 'levels': levels, 'weighting': weighting, 'min_freq': min_freq,
            'max_terms': max_terms, 'alpha': a, 'early': bool(early), 'n_docs': len(keep), 'n_terms': len(cols), 'lambda': F['lambda'],
            'lam_max': F['lam_max'], 'aicc': F['aicc'], 'steps': len(path), 'best_step': F['best'], 'intercept': b0, 'terms': terms_out,
            'path': [{'lambda': p['lambda'], 'aicc': p['aicc'], 'nonzero': p['nonzero']} for p in path], 'note': note,
            'docs': {'rows': doc_rows, 'positive': pos, 'negative': neg, 'predicted': pred, 'actual': y},
            'doc_labels': [C.labels[d] for d in keep] if id_col else None,
            'code': '\n'.join(code), 'plot_code': _dated({'bars': bars} if bars else {}, table)}


# ---------------------------------------------------------------------------
# Sentiment Analysis: VADER's lexicon and rules (vaderSentiment, MIT, fetched at run time)
# ---------------------------------------------------------------------------

VADER = 'vaderSentiment'


@api('text.sentiment', packages=SK)
def sentiment(table, column, rows=None, id_col=None, where=None, table_name='data', **read):
    """Sentiment Analysis by VADER (Hutto and Gilbert 2014): each
    document's positive, neutral and negative shares and compound score
    (its lexicon's valences, with negators, intensifiers, capitals, '!'
    and 'but' taken into account); the summary, the sentiment, negation
    and intensifier terms met, the histogram's code. English only. The
    package comes from PyPI at run time (the page fetches the wheel,
    checks its pinned sha256 and installs it with micropip): its lexicon
    is never part of this site."""
    try:
        from vaderSentiment import vaderSentiment as vs
    except ImportError:
        return {'error': 'Sentiment Analysis needs the vaderSentiment package (MIT) from PyPI, which is not installed here', 'missing': VADER}
    try:
        cfg = _read(read)
        C = _corpus(table, column, rows, id_col, cfg)
    except ValueError as e:
        return {'error': str(e)}

    def build():
        import string
        an = vs.SentimentIntensityAnalyzer()
        texts = ['\n'.join(C.texts[i] for i in d if C.texts[i]) for d in C.docs]
        sc = [an.polarity_scores(t) for t in texts]
        # the terms met, as VADER reads its words (split at spaces, punctuation stripped, lowercase):
        # sentiment terms (its lexicon), negations (its list, or n't) and intensifiers (its boosters)
        lex, neg, boost = {}, {}, {}
        negate = set(vs.NEGATE)
        for d, t in enumerate(texts):
            for w in (x.strip(string.punctuation) for x in t.lower().split()):
                if not w:
                    continue
                for store, hit in ((lex, w in an.lexicon), (boost, w in vs.BOOSTER_DICT), (neg, w in negate or "n't" in w)):
                    if hit:
                        e = store.setdefault(w, [0, set()])
                        e[0] += 1
                        e[1].add(d)
        return {'scores': sc, 'lex': lex, 'neg': neg, 'boost': boost, 'valence': {w: float(an.lexicon[w]) for w in lex},
                'lexicon_size': len(an.lexicon)}
    spec = {'column': column, 'id': id_col, **cfg}
    F = predictive.cached('text.sentiment', table, rows, spec, build)
    sc = F['scores']
    comp = np.array([s['compound'] for s in sc], dtype=float)
    pos_n, neg_n = int(np.sum(comp >= 0.05)), int(np.sum(comp <= -0.05))
    empty = [d for d, doc in enumerate(C.docs) if not any(C.texts[i].strip() for i in doc)]
    lexicon = sorted(({'term': w, 'score': F['valence'][w], 'count': c, 'docs': len(ds), 'd': sorted(ds)} for w, (c, ds) in F['lex'].items()),
                     key=lambda r: (-r['count'], r['term']))
    vader = 'from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer   # MIT; pip install vaderSentiment==3.3.2 (in the notebook: %pip install vaderSentiment==3.3.2)'
    head = _code_read(table, table_name, column, rows, id_col, ['import numpy as np', 'import pandas as pd', vader], where)
    docs_lines = ([f'texts = df.groupby({_py(id_col)}, sort=False)[{_py(column)}].apply(lambda s: "\\n".join(t for t in s if t))   # a document: the texts of its rows'] if id_col
                  else [f'texts = df[{_py(column)}]   # each row a document'])
    core = docs_lines + [
        'analyzer = SentimentIntensityAnalyzer()',
        'scores = pd.DataFrame([analyzer.polarity_scores(t) for t in texts])   # neg, neu, pos (shares of the text) and compound (-1 to 1)']
    code = head + core + [
        'label = np.where(scores["compound"] >= 0.05, "positive", np.where(scores["compound"] <= -0.05, "negative", "neutral"))   # VADER\'s thresholds',
        'print(pd.Series(label).value_counts())', 'print(scores["compound"].describe())']
    hist = '\n'.join(_code_read(table, table_name, column, rows, id_col, ['import numpy as np', 'import pandas as pd', 'import matplotlib.pyplot as plt', vader], where) + core + [
        'edges = np.linspace(-1, 1, 21)   # bins of 0.1',
        'fig, ax = plt.subplots(figsize=(4.4, 2.8), layout="constrained")',
        f'ax.hist(scores["compound"], bins=edges, color="#8fa9c2", edgecolor="white", linewidth=0.5)',
        'ax.set_xlabel("Compound score")', 'ax.set_ylabel("Documents")', 'ax.set_title("Sentiment of the documents")', 'plt.show()'])
    table_of = lambda store: sorted(({'term': w, 'count': c, 'docs': len(ds), 'd': sorted(ds), **({'multiplier': float(vs.BOOSTER_DICT[w])} if store is F['boost'] else {})}   # noqa: E731
                                     for w, (c, ds) in store.items()), key=lambda r: (-r['count'], r['term']))
    import importlib.metadata as md
    try:
        version = md.version(VADER)
    except Exception:  # noqa: BLE001
        version = None
    return {'column': column, 'n_docs': C.n_docs, 'empty': len(empty), 'version': version, 'lexicon_size': F['lexicon_size'],
            'summary': {'positive': pos_n, 'negative': neg_n, 'neutral': C.n_docs - pos_n - neg_n, 'mean': float(np.mean(comp)) if len(comp) else None,
                        'mean_pos': float(np.mean(comp[comp >= 0.05])) if pos_n else None, 'mean_neg': float(np.mean(comp[comp <= -0.05])) if neg_n else None},
            'docs': {'rows': [[int(C.rows[i]) for i in d] for d in C.docs], 'pos': [s['pos'] for s in sc], 'neu': [s['neu'] for s in sc],
                     'neg': [s['neg'] for s in sc], 'compound': comp,
                     # each document's bar of the histogram, as np.histogram bins it (the last bin closed)
                     'bin': np.clip(np.searchsorted(np.linspace(-1, 1, 21), comp, side='right') - 1, 0, 19)},
            'doc_labels': C.labels if id_col else None, 'lexicon': lexicon, 'negations': table_of(F['neg']), 'intensifiers': table_of(F['boost']),
            'code': '\n'.join(code), 'plot_code': _dated({'hist': hist}, table)}
