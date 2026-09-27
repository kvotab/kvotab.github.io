#!/usr/bin/env python3
"""Analyze > Text Explorer's backend (resources/py/smui/text.py), checked
against Porter's (1980) paper (every example of every step, the measure m,
the consonants, the two worked examples), scikit-learn's ENGLISH_STOP_WORDS
and CountVectorizer called directly, counts made here another way (tokens,
terms, phrases, the rows of each, the summary), JMP's documented weightings
computed by formula on a dense matrix, numpy's SVD of that matrix (every
centering), statsmodels' varimax (factor_rotation.rotate_factors) and the
varimax criterion, scikit-learn's NMF and LatentDirichletAllocation called
directly, and by running the Python shown under each result on a CSV export
of the table. It also times the defaults on 5,000 rows.

    python3 resources/tests/smui/test_text.py
"""
import collections
import contextlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np
import pandas as pd
from sklearn.decomposition import NMF, PCA, LatentDirichletAllocation, TruncatedSVD
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer
from statsmodels.multivariate.factor_rotation import rotate_factors

from backend import FAILED, Checks, call, table

check = Checks()
check('text.py imports', 'text' in FAILED, False)
from smui import text as TX  # noqa: E402

STOP = ENGLISH_STOP_WORDS
DOT = '\u00b7'


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float)))) if np.size(a) else 0.0


# ---- the Porter stemmer: every example of the paper -------------------------------------------------------------
P = TX.PorterStemmer()
check('consonants: in TOY they are T and Y', [c for c, k in zip('toy', P.consonants('toy')) if k], ['t', 'y'])
check('consonants: in SYZYGY they are S, Z and G', [c for c, k in zip('syzygy', P.consonants('syzygy')) if k], ['s', 'z', 'g'])
for m_, words in ((0, 'tr ee tree y by'), (1, 'trouble oats trees ivy'), (2, 'troubles private oaten orrery')):
    check(f'the measure m = {m_}: {words}', [P.measure(w) for w in words.split()], [m_] * len(words.split()))
STEPS = {
    'step1a': 'caresses caress; ponies poni; ties ti; caress caress; cats cat',
    'step1b': 'feed feed; agreed agree; plastered plaster; bled bled; motoring motor; sing sing; conflated conflate; troubled trouble; '
              'sized size; hopping hop; tanned tan; falling fall; hissing hiss; fizzed fizz; failing fail; filing file',
    'step1c': 'happy happi; sky sky',
    'step2': 'relational relate; conditional condition; rational rational; valenci valence; hesitanci hesitance; digitizer digitize; '
             'conformabli conformable; radicalli radical; differentli different; vileli vile; analogousli analogous; vietnamization vietnamize; '
             'predication predicate; operator operate; feudalism feudal; decisiveness decisive; hopefulness hopeful; callousness callous; '
             'formaliti formal; sensitiviti sensitive; sensibiliti sensible',
    'step3': 'triplicate triplic; formative form; formalize formal; electriciti electric; electrical electric; hopeful hope; goodness good',
    'step4': 'revival reviv; allowance allow; inference infer; airliner airlin; gyroscopic gyroscop; adjustable adjust; defensible defens; '
             'irritant irrit; replacement replac; adjustment adjust; dependent depend; adoption adopt; homologou homolog; communism commun; '
             'activate activ; angulariti angular; homologous homolog; effective effect; bowdlerize bowdler',
    'step5a': 'probate probat; rate rate; cease ceas',
    'step5b': 'controll control; roll roll',
}
for step, pairs in STEPS.items():
    got = []
    want = []
    for pair in pairs.split('; '):
        w, s = pair.split()
        got.append(getattr(P, step)(w))
        want.append(s)
    check(f'Porter (1980) {step}: the paper\'s {len(want)} examples', got, want)
check('the paper\'s worked examples: generalizations -> gener, oscillators -> oscil', [P.stem('generalizations'), P.stem('oscillators')], ['gener', 'oscil'])
FULL = ('caresses caress, ponies poni, ties ti, cats cat, feed feed, agreed agre, plastered plaster, bled bled, motoring motor, sing sing, '
        'conflated conflat, troubled troubl, sized size, hopping hop, tanned tan, falling fall, hissing hiss, fizzed fizz, failing fail, filing file, '
        'happy happi, sky sky, relational relat, conditional condit, rational ration, valenci valenc, hesitanci hesit, digitizer digit, '
        'conformabli conform, radicalli radic, differentli differ, vileli vile, analogousli analog, vietnamization vietnam, predication predic, '
        'operator oper, feudalism feudal, decisiveness decis, hopefulness hope, callousness callous, formaliti formal, sensitiviti sensit, '
        'sensibiliti sensibl, triplicate triplic, formative form, formalize formal, electriciti electr, electrical electr, hopeful hope, goodness good, '
        'revival reviv, allowance allow, inference infer, airliner airlin, gyroscopic gyroscop, adjustable adjust, defensible defens, irritant irrit, '
        'replacement replac, adjustment adjust, dependent depend, adoption adopt, homologou homolog, communism commun, activate activ, '
        'angulariti angular, homologous homolog, effective effect, bowdlerize bowdler, probate probat, rate rate, cease ceas, controll control, roll roll')
pairs = [p.split() for p in FULL.split(', ')]
bad = [(w, P.stem(w), s) for w, s in pairs if P.stem(w) != s]
check(f'the whole algorithm on every example word of the paper ({len(pairs)} words)', bad, [])
check('words of one or two letters are left as they are (as Porter\'s own implementation)', [P.stem(w) for w in ('is', 'as', 'us', 'a')], ['is', 'as', 'us', 'a'])
check('a word with other characters than a-z is left as it is', [P.stem(w) for w in ("don't", 'well-known', 'mp3s', 'café', 'Cats')], ["don't", 'well-known', 'mp3s', 'café', 'Cats'])
check('the stems are remembered', P.memo.get('oscillators'), 'oscil')
check('a run of y does not recurse (a word of 5,000 letters)', P.stem('y' * 5000) == P.stem('y' * 5000), True)

# ---- the stop words are scikit-learn's, read at run time ------------------------------------------------------------------------------
src = open(TX.__file__, encoding='utf-8').read()
check('text.py holds no copy of the stop words (sklearn\'s own misspelling "amoungst" is not in it)', 'amoungst' in src, False)
common = [w for w in sorted(STOP) if len(w) > 5]
check('nor a run of them', sum(1 for w in common if re.search(rf"['\"]{w}['\"]", src)), 0)
r = call('text.explore', table=table({'t': ['The cat and the hat, with a dog']}), column='t')
check('the stop words the report lists are scikit-learn\'s ENGLISH_STOP_WORDS', r['stop_words'], sorted(STOP))
check('and they are left out of the terms', [x['term'] for x in r['terms']], ['cat', 'dog', 'hat'])

# ---- the tokenizers --------------------------------------------------------------------------------------------------------------------------------
def toks(text, **kw):
    return TX.read_terms([text], frozenset(), **kw)[0][0]


s = "Visit https://shop.example.com/a?b=1. Mail anna.b+x@mail.example.org! 3.5 kg, 1,000 items; 25% off. 3d mp3 2nd don't well-known customer's Customers’ it’s"
check('Regex: URLs (a full stop after one dropped), e-mail addresses, numbers, words with inner apostrophes and hyphens, possessives dropped',
      toks(s), ['visit', 'https://shop.example.com/a?b=1', 'mail', 'anna.b+x@mail.example.org', '3.5', 'kg', '1,000', 'items', '25%', 'off',
                '3d', 'mp3', '2nd', "don't", 'well-known', 'customer', 'customers', 'it'])
check('Basic Words: runs of letters and digits', toks(s, tokenizing='basic')[:12],
      ['visit', 'https', 'shop', 'example', 'com', 'a', 'b', '1', 'mail', 'anna', 'b', 'x'])
check('Basic Words splits at apostrophes and hyphens', toks("don't well-known", tokenizing='basic'), ['don', 't', 'well', 'known'])
check('letters of any alphabet are words', toks('Größe café Ünïcode'), ['größe', 'café', 'ünïcode'])
check('a custom regex: every match is a token', toks('ab12 cd34, ef', regex=r'[a-z]+\d*'), ['ab12', 'cd34', 'ef'])
check('a custom regex with groups: the whole match', toks('x-1 y-2', regex=r'([a-z])-(\d)'), ['x-1', 'y-2'])
check('a custom regex that matches nothing: no tokens, no hang', toks('abc', regex=r'\d*'), [])
check('Minimum and Maximum Characters per Word', toks('a an ant ants antsy', min_chars=2, max_chars=4), ['an', 'ant', 'ants'])
check('Customize Regex is for the Regex tokenizer only', call('text.explore', table=table({'t': ['a1 b2']}), column='t', tokenizing='basic', regex=r'\d')['settings']['regex'], None)
check('a regex that does not compile: an error that says so', 'does not compile' in call('text.explore', table=table({'t': ['x']}), column='t', regex='(a')['error'], True)
check('a pathological text is quick (backtracking bounded)', (lambda t0: (toks('a.' * 20000 + '1' * 20000 + 'x'), time.time() - t0)[1] < 2)(time.time()), True)

# ---- the terms, the lists and the summary against counts made here ------------------------------------------------------------------------
VOC = ('delivery arrived late early parcel courier damaged broken quality refund return service staff helpful rude waited phone price cheap '
       'expensive value money discount app website checkout crashed slow login the a and was is it very but not too for with of on to my').split()
rng = np.random.default_rng(20260927)


def sentence(r):
    w = [VOC[i] for i in r.integers(len(VOC), size=r.integers(2, 12))]
    out = ' '.join(w)
    if r.random() < 0.3:
        out = out.upper() if r.random() < 0.2 else out.capitalize()
    return out + r.choice(['.', '!', ', ', '; ', '?', ''])


texts = [None if rng.random() < 0.04 else ''.join(sentence(rng) for _ in range(rng.integers(1, 4))) for _ in range(400)]
texts[5] = '   '
groups = [f'g{i % 3}' for i in range(400)]
tid = table({'comment': texts, 'g': groups, 'customer': [f'c{int(i)}' for i in rng.integers(0, 150, 400)], 'num': np.arange(400.0)})


def ref_tokens(t):
    return re.findall(r'[a-z0-9]+', (t or '').lower())


RT = [ref_tokens(t) for t in texts]
RTERMS = [[w for w in ts if w not in STOP] for ts in RT]
cnt = collections.Counter(w for ts in RTERMS for w in ts)
res = call('text.explore', table=tid, column='comment')
got = {x['term']: x['count'] for x in res['terms']}
check('the Term List: every term and its count as counted here', got, dict(cnt))
order = sorted(cnt, key=lambda w: (-cnt[w], w))
check('sorted by count, then alphabetically', [x['term'] for x in res['terms']], order)
docs_with = collections.Counter(w for ts in RTERMS for w in set(ts))
check('each term\'s cases (documents that hold it)', {x['term']: x['cases'] for x in res['terms']}, dict(docs_with))
rows_of = {w: [i for i, ts in enumerate(RTERMS) if w in ts] for w in cnt}
check('the rows that hold each term (for selecting them)', all(res['term_rows'][k] == rows_of[x['term']] for k, x in enumerate(res['terms'])), True)
ntok = sum(cnt.values())
nonempty = sum(1 for ts in RTERMS if ts)
check('Summary Counts: Number of Terms, Number of Cases, Total Tokens', (res['summary']['terms'], res['summary']['cases'], res['summary']['tokens']), (len(cnt), 400, ntok))
check.near('Tokens per Case = Total Tokens / Number of Cases', res['summary']['tokens_per_case'], ntok / 400)
check.near('Portion Non-empty: the cases with a term', res['summary']['portion_nonempty'], nonempty / 400)
check('rows with no text are counted and said so', any(n.startswith(f'{sum(1 for t in texts if not (t or "").strip())} of the 400 rows have no text') for n in res['notes']), True)
check('Regex and Basic Words agree on plain words', call('text.explore', table=tid, column='comment', tokenizing='basic')['terms'], res['terms'])
vec = CountVectorizer(analyzer=lambda d: d)
Xref = vec.fit_transform(RTERMS)
check('the counts are CountVectorizer\'s over the terms', {t: int(c) for t, c in zip(vec.get_feature_names_out(), np.asarray(Xref.sum(0)).ravel())}, dict(cnt))


def ref_phrases(tokens, stop, max_words):
    c = collections.Counter()
    rows = collections.defaultdict(set)
    for i, ts in enumerate(tokens):
        for n in range(2, max_words + 1):
            for a in range(len(ts) - n + 1):
                g = ts[a:a + n]
                if g[0] not in stop and g[-1] not in stop:
                    c[' '.join(g)] += 1
                    rows[' '.join(g)].add(i)
    return c, rows


pc, prows = ref_phrases(RT, STOP, 4)
want = sorted((p for p in pc if pc[p] > 1), key=lambda p: (-pc[p], p))
check('the Phrase List: 2 to 4 words, not beginning or ending with a stop word, seen twice, as counted here', [(x['phrase'], x['count'], x['n']) for x in res['phrases']],
      [(p, pc[p], len(p.split())) for p in want][:1000])
check('the rows that hold each phrase', all(res['phrase_rows'][k] == sorted(prows[x['phrase']]) for k, x in enumerate(res['phrases'])), True)
r2 = call('text.explore', table=tid, column='comment', max_words=2, max_phrases=15)
check('Maximum Words per Phrase and Maximum Number of Phrases', [(x['phrase'], x['count']) for x in r2['phrases']],
      [(p, pc[p]) for p in want if len(p.split()) == 2][:15])
check('one word per phrase: no phrases', call('text.explore', table=tid, column='comment', max_words=1)['phrases'], [])
rr = call('text.explore', table=tid, column='comment', rows=list(range(0, 400, 3)))
cr = collections.Counter(w for i, ts in enumerate(RTERMS) if i % 3 == 0 for w in ts)
check('a row list (a By group, exclusions) limits the counts', ({x['term']: x['count'] for x in rr['terms']}, rr['summary']['cases']), (dict(cr), len(range(0, 400, 3))))
check('and the rows of each term are the page\'s row numbers', rr['term_rows'][0] == [i for i in range(0, 400, 3) if rr['terms'][0]['term'] in RTERMS[i]], True)

# ---- stop words, recodes and phrases of the user --------------------------------------------------------------------------------------------
top1, top2 = order[0], order[1]
ru = call('text.explore', table=tid, column='comment', stop_add=[top1.upper() + ' '])
check('Add Stop Word: the term is gone, the others keep their counts', ({x['term']: x['count'] for x in ru['terms']}, ru['user_stop']), ({w: c for w, c in cnt.items() if w != top1}, [top1]))
pu, _ = ref_phrases(RT, STOP | {top1}, 4)
check('and no phrase begins or ends with it', [(x['phrase'], x['count']) for x in ru['phrases']][:50], [(p, pu[p]) for p in sorted((p for p in pu if pu[p] > 1), key=lambda p: (-pu[p], p))][:50])
rc = call('text.explore', table=tid, column='comment', recodes={top2: top1})
check('Recode: the two terms count as one', {x['term']: x['count'] for x in rc['terms']}.get(top1), cnt[top1] + cnt[top2])
check('and the recoded term lists its words', sorted(w for w, _ in rc['forms'][top1]), sorted([top2]))
ph = want[0]
ra = call('text.explore', table=tid, column='comment', phrases=[ph])
a_, b_ = ph.split()[0], ph.split()[-1]
joined = TX.join_phrases(RT, [ph])
cj = collections.Counter(w for ts in joined for w in ts if w not in STOP)
check(f'Add Phrase ("{ph}"): the phrase is a term with its count', {x['term']: x['count'] for x in ra['terms']}.get(ph), pc[ph])
check('and its words lose the occurrences inside it', {x['term']: x['count'] for x in ra['terms']}, dict(cj))
check('join_phrases: the longest phrase first', TX.join_phrases([['a', 'b', 'c', 'a', 'b']], ['a b', 'a b c']), [['a b c', 'a b']])
check('a phrase of one word is not a phrase', call('text.explore', table=tid, column='comment', phrases=['delivery'])['added_phrases'], [])

# ---- stemming -------------------------------------------------------------------------------------------------------------------------------------------
st_texts = ['I returned it and they are returning it', 'Return policy: returns accepted', 'The delivery was quick', 'Deliveries delivered late',
            'The app crashed', 'Crashing again, crashes daily', 'good goods']
tst = table({'t': st_texts})
rn = call('text.explore', table=tst, column='t')
rs = call('text.explore', table=tst, column='t', stemming='combine')
ra_ = call('text.explore', table=tst, column='t', stemming='all')
cs = {x['term']: x['count'] for x in rs['terms']}
check('Stem for Combining: words that share a stem become one stemmed term, marked with a dot', (cs.get('return' + DOT), cs.get('crash' + DOT), cs.get('good' + DOT)), (4, 3, 2))
check('a word alone with its stem is left as it is', ('quick' in cs, 'quick' + DOT in cs, 'app' in cs, 'polici' + DOT in cs), (True, False, True, False))
check('delivered has a stem of its own (deliv) and stays as it is', (cs.get('deliv' + DOT), 'delivered' in cs, 'delivery' in cs), (None, True, False))
check('Porter: deliveries -> deliveri, delivered -> deliv, delivery -> deliveri', [P.stem(w) for w in ('deliveries', 'delivered', 'delivery')], ['deliveri', 'deliv', 'deliveri'])
check('so deliveries and delivery combine', cs.get('deliveri' + DOT), 2)
ca = {x['term']: x['count'] for x in ra_['terms']}
check('Stem All Terms: every word of three or more letters a-z is stemmed', all(t.endswith(DOT) for t in ca), True)
check('the stem of every word, counted', ca, dict(collections.Counter(P.stem(w) + DOT for t in st_texts for w in ref_tokens(t) if w not in STOP)))
check('the total count is unchanged by stemming', (rn['summary']['tokens'], rs['summary']['tokens'], ra_['summary']['tokens']), (rn['summary']['tokens'],) * 3)
stem_rep = {x['stem']: x['forms'] for x in rs['stems']}
check('the Stem Report: the words of each stem, with their counts', stem_rep['return' + DOT], [['return', 1], ['returned', 1], ['returning', 1], ['returns', 1]])
check('and Show Text\'s words for a stemmed term', sorted(w for w, _ in rs['forms']['crash' + DOT]), ['crashed', 'crashes', 'crashing'])
rsu = call('text.explore', table=tst, column='t', stemming='combine', stop_add=['crash' + DOT])
check('a stemmed term as a stop word drops all its words', any(x['term'].startswith('crash') for x in rsu['terms']), False)

# ---- documents made of the rows that share an ID ----------------------------------------------------------------------------------------------
ri = call('text.explore', table=tid, column='comment', id_col='customer')
ids = list(dict.fromkeys(call('text.explore', table=tid, column='comment', id_col='customer')['doc_labels']))
check('with an ID: one case per ID, in the order they first come', ri['summary']['cases'], len(ids))
cust_vals = [v for v in __import__('smui').data.raw(tid, 'customer')]
dterms = collections.OrderedDict()
for c_, ts in zip(cust_vals, RTERMS):
    dterms.setdefault(c_, []).extend(ts)
check('the ID\'s rows make one document', ids, list(dterms))
check('its cases and counts', ({x['term']: x['cases'] for x in ri['terms']}, ri['summary']['nonempty']),
      (dict(collections.Counter(w for ts in dterms.values() for w in set(ts))), sum(1 for ts in dterms.values() if ts)))
check('but a term\'s rows are the rows whose own text holds it', ri['term_rows'] == res['term_rows'], True)
tmiss = table({'t': ['red apple', 'green apple', 'red pear', 'blue'], 'id': [1, None, 1, 2]})
rm = call('text.explore', table=tmiss, column='t', id_col='id')
check('numeric IDs; rows with no ID are left out, and said so', (rm['summary']['cases'], rm['doc_labels'], rm['notes']), (2, ['1', '2'], ['1 rows with no id are left out.']))
check('a numeric text column: an error', call('text.explore', table=tid, column='num')['error'], 'num is numeric: Text Explorer reads character columns')
check('only English', 'English' in call('text.explore', table=tid, column='comment', language='german')['error'], True)
check('bad settings: errors that name them', ['Maximum Words per Phrase' in call('text.explore', table=tid, column='comment', max_words=0)['error'],
      'Maximum Characters per Word' in call('text.explore', table=tid, column='comment', min_chars=5, max_chars=2)['error'],
      'Stemming' in call('text.explore', table=tid, column='comment', stemming='lots')['error']], [True, True, True])
check('an empty column: no terms, no error', call('text.explore', table=table({'t': ['', None, 'the a']}), column='t')['summary']['terms'], 0)

# ---- the document term matrix: JMP's weightings by formula ------------------------------------------------------------------------------
chosen = [w for w in order if cnt[w] >= 2][:60]
C = np.array([[collections.Counter(ts)[w] for w in chosen] for ts in RTERMS], dtype=float)
nd = (C > 0).sum(axis=0)
REF_W = {'binary': (C > 0) * 1.0, 'ternary': np.where(C > 1, 2.0, np.where(C > 0, 1.0, 0.0)), 'frequency': C,
         'logfreq': np.log10(1 + C), 'tfidf': C * np.log(400 / nd)}
for w, M in REF_W.items():
    d = call('text.dtm', table=tid, column='comment', weighting=w, min_freq=2, max_terms=60)
    check(f'Save Document Term Matrix, {TX.WEIGHTINGS[w]}: the formula\'s values', (d['terms'] == chosen, mx(np.array(d['values']).T, M) < 1e-12), (True, True))
d = call('text.dtm', table=tid, column='comment', terms=[order[5], 'nosuchterm', order[2]])
check('the chosen terms, in their order (unknown ones dropped)', d['terms'], [order[5], order[2]])
dd = call('text.dtm', table=tid, column='comment', id_col='customer', weighting='frequency', max_terms=3)
check('with an ID every row gets its document\'s value', all(dd['values'][0][k] == sum(1 for c_, ts in zip(cust_vals, RTERMS) if c_ == cust_vals[r_] for w in ts if w == dd['terms'][0])
                                                            for k, r_ in enumerate(dd['rows'])), True)

# ---- latent semantic analysis against numpy's SVD ----------------------------------------------------------------------------------------------
def ref_svd(M, k, centering):
    A = M.copy()
    if centering != 'uncentered':
        A = A - A.mean(axis=0)
        if centering == 'scaled':
            sd = M.std(axis=0, ddof=1)
            sd[sd <= 1e-12 * sd.max()] = 1.0
            A = A / sd
    U, s, Vt = np.linalg.svd(A, full_matrices=False)
    U, s, V = U[:, :k], s[:k], Vt[:k].T
    flip = np.sign((V * s)[np.abs(V).argmax(axis=0), np.arange(k)])
    return U * s * flip, V * s * flip, s, float((A ** 2).sum())


M = REF_W['tfidf']
for centering in ('centered', 'uncentered', 'scaled'):
    L = call('text.lsa', table=tid, column='comment', weighting='tfidf', centering=centering, min_freq=2, max_terms=60, k=8, show=8, seed=3)
    D, T, s, tot = ref_svd(M, 8, centering)
    check(f'LSA, {TX.CENTERING[centering]}: the terms of the matrix', L['terms'], chosen)
    check.near(f'LSA, {TX.CENTERING[centering]}: the singular values are numpy\'s SVD of the dense matrix', mx([x['value'] for x in L['singular']], s), 0.0, abs_=1e-8 * s[0])
    check.near(f'LSA, {TX.CENTERING[centering]}: the documents\' coordinates U S', mx(np.array(L['docs']).T, D), 0.0, abs_=1e-7 * s[0])
    check.near(f'LSA, {TX.CENTERING[centering]}: the terms\' coordinates V S', mx(np.array(L['term_vectors']).T, T), 0.0, abs_=1e-7 * s[0])
    check.near(f'LSA, {TX.CENTERING[centering]}: Percent is each s² over the matrix\'s sum of squares', mx([x['percent'] for x in L['singular']], 100 * s ** 2 / tot), 0.0, abs_=1e-9)
    check.near(f'LSA, {TX.CENTERING[centering]}: Cum Percent', L['singular'][-1]['cum'], 100 * np.sum(s ** 2) / tot, rel=1e-9)
check('each vector\'s largest term coordinate is positive', all(max(v, key=abs) > 0 for v in L['term_vectors']), True)
Xs = TX.weigh(Xref, 'tfidf')
p_ = PCA(n_components=5, svd_solver='covariance_eigh').fit(Xs)
t_ = TruncatedSVD(n_components=5, algorithm='arpack', random_state=0).fit(Xs.toarray() - Xs.toarray().mean(axis=0))
check.near('PCA on the sparse matrix = TruncatedSVD of the dense centered matrix (scikit-learn, both)', mx(p_.singular_values_, t_.singular_values_), 0.0, abs_=1e-9 * p_.singular_values_[0])
Lb = call('text.lsa', table=tid, column='comment', min_freq=1, max_terms=1000, k=1000)
check('the number of singular vectors is cut to the matrix (documents − 1, terms − 1)', Lb['k'], min(400 - 1, len(cnt) - 1))
Ld = call('text.lsa', table=tid, column='comment')
check('JMP\'s defaults: TF IDF, Centered, terms seen 4 or more times', (Ld['weighting'], Ld['centering'], Ld['n_terms']), ('tfidf', 'centered', sum(1 for w in cnt if cnt[w] >= 4)))
check('too few terms for an SVD: an error', 'SVD needs two or more' in call('text.lsa', table=tid, column='comment', min_freq=10 ** 6)['error'], True)
Li = call('text.lsa', table=tid, column='comment', id_col='customer', min_freq=2, max_terms=40, k=4)
check('with an ID one point per document, with its rows', (len(Li['docs'][0]), sum(len(r_) for r_ in Li['doc_rows'])), (len(ids), 400))

# ---- varimax against statsmodels, and the topics ---------------------------------------------------------------------------------------------------
from statsmodels.multivariate.factor_rotation.tests.test_rotation import TestWrappers  # noqa: E402
A8 = TestWrappers.get_A() if isinstance(TestWrappers.__dict__.get('get_A'), classmethod) else TestWrappers().get_A()


def crit(L):
    L2 = L ** 2
    return float(np.sum(L2.var(axis=0) * L.shape[0]))   # the raw varimax criterion (up to a constant)


def aligned(Z, W):
    """Columns of W put in Z's order and sign."""
    out = np.zeros_like(W)
    used = set()
    for j in range(Z.shape[1]):
        c = [abs(float(Z[:, j] @ W[:, q])) if q not in used else -1 for q in range(W.shape[1])]
        q = int(np.argmax(c))
        used.add(q)
        out[:, j] = W[:, q] * np.sign(Z[:, j] @ W[:, q])
    return out


for name, A in (('Harman\'s eight physical variables (statsmodels\' test matrix)', A8), ('a random 30 × 4 matrix', np.random.default_rng(4).normal(size=(30, 4)))):
    Z, R = TX.varimax(A, normalize=False, eps=1e-12)
    Lsm, Tsm = rotate_factors(A, 'varimax', tol=1e-12)
    check.near(f'varimax without normalization = statsmodels rotate_factors(varimax), {name}', mx(Z, aligned(Z, Lsm)), 0.0, abs_=2e-5)
    check.near(f'the rotation is orthogonal, {name}', mx(R.T @ R, np.eye(R.shape[0])), 0.0, abs_=1e-12)
    check(f'and it raises the varimax criterion, {name}', crit(Z) >= crit(A) - 1e-12, True)
    Zk, Rk = TX.varimax(A, eps=1e-12)
    h = np.sqrt((A ** 2).sum(axis=1))
    Ln, _ = rotate_factors(A / h[:, None], 'varimax', tol=1e-12)
    check.near(f'Kaiser\'s normalization: statsmodels\' varimax of the rows scaled to 1, scaled back, {name}', mx(Zk, aligned(Zk, Ln * h[:, None])), 0.0, abs_=2e-5)
    check.near(f'the communalities are kept, {name}', mx((Zk ** 2).sum(axis=1), (A ** 2).sum(axis=1)), 0.0, abs_=1e-12)
check('one topic: no rotation', TX.varimax(np.ones((3, 1)))[1].tolist(), [[1.0]])
Tp = call('text.topics', table=tid, column='comment', n_topics=4, min_freq=2, max_terms=60, top=5, scores=4, seed=3)
D, Tv, s4, tot = ref_svd(M, 4, 'centered')
load = np.array(Tp['loadings']).T
sc = np.array(Tp['scores']).T
check.near('topic scores times loadings = the SVD\'s rank-4 fit', mx(sc @ load.T, D @ (Tv / s4).T), 0.0, abs_=1e-8)
check.near('the scores have mean 0 and variance 1 (centered)', max(mx(sc.mean(axis=0), 0), mx(sc.var(axis=0, ddof=1), 1)), 0.0, abs_=1e-9)
_, Rr = TX.varimax(Tv, eps=1e-5)
check.near('the loadings are V S R / sqrt(n - 1), R varimax of V S', mx(load, aligned(load, Tv @ Rr / math.sqrt(399))), 0.0, abs_=1e-9)
var = [v['variance'] for v in Tp['variance']]
check('largest topic first, each signed so that its largest loading is positive', (var == sorted(var, reverse=True), all(max(c, key=abs) > 0 for c in load.T)), (True, True))
check.near('the rotation keeps the variance the SVD explains', sum(var), float(np.sum(s4 ** 2)), rel=1e-9)
check('Top Loadings by Topic: the terms with the largest loadings', [[x['term'] for x in tp] for tp in Tp['top']],
      [[chosen[j] for j in np.argsort(-load[:, t], kind='stable')[:5]] for t in range(4)])
Xw = TX.weigh(Xref[:, [vec.vocabulary_[w] for w in chosen]], 'tfidf')
nm = NMF(n_components=4, init='nndsvda', max_iter=500, random_state=3)
W_ = nm.fit_transform(Xw)
H_ = nm.components_.T
o_ = np.argsort(-(W_.sum(0) * H_.sum(0)), kind='stable')
Tn = call('text.topics', table=tid, column='comment', method='nmf', n_topics=4, min_freq=2, max_terms=60, scores=4, seed=3)
check.near('NMF: scikit-learn\'s NMF called directly (the largest topic first)', max(mx(np.array(Tn['loadings']).T, H_[:, o_]), mx(np.array(Tn['scores']).T, W_[:, o_])), 0.0, abs_=1e-9)
ld = LatentDirichletAllocation(n_components=3, learning_method='batch', random_state=3)
Xc = Xref[:, [vec.vocabulary_[w] for w in chosen]].astype(float)
G_ = ld.fit_transform(Xc)
Hl = (ld.components_ / ld.components_.sum(axis=1, keepdims=True)).T
o_ = np.argsort(-G_.sum(0), kind='stable')
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    Tl = call('text.topics', table=tid, column='comment', method='lda', n_topics=3, min_freq=2, max_terms=60, scores=3, seed=3)
check('LDA reports each of its 10 EM iterations as it goes (smui:progress lines)', [ln for ln in buf.getvalue().splitlines() if ln.startswith('smui:progress')], [f'smui:progress lda {i} 10' for i in range(1, 11)])
check.near('LDA: scikit-learn\'s LatentDirichletAllocation on the counts, called directly', max(mx(np.array(Tl['loadings']).T, Hl[:, o_]), mx(np.array(Tl['scores']).T, G_[:, o_])), 0.0, abs_=1e-9)
with contextlib.redirect_stdout(io.StringIO()):
    lw = call('text.topics', table=tid, column='comment', method='lda', n_topics=2, weighting='tfidf', min_freq=2)['weighting']
check('LDA takes the counts (Frequency) whatever the weighting', lw, 'frequency')
check.near('each LDA topic\'s term probabilities sum to 1', mx(np.array(Tl['loadings']).sum(axis=1), 1), 0.0, abs_=1e-12)
v_ = call('text.vectors', table=tid, column='comment', kind='svd', min_freq=2, max_terms=60, k=8, count=3, seed=3)
L8 = call('text.lsa', table=tid, column='comment', min_freq=2, max_terms=60, k=8, show=3, seed=3)
check('Save Document Singular Vectors: the first 3 for every row', (len(v_['values']), v_['rows'] == list(range(400)), mx(v_['values'], L8['docs'])), (3, True, 0.0))
vt = call('text.vectors', table=tid, column='comment', kind='topics', n_topics=4, min_freq=2, max_terms=60, count=2, seed=3, id_col='customer')
Ti = call('text.topics', table=tid, column='comment', n_topics=4, min_freq=2, max_terms=60, scores=2, seed=3, id_col='customer')
dpos = {r_: d for d, rs_ in enumerate(Ti['doc_rows']) for r_ in rs_}
check('Save Topic Scores with an ID: each row its document\'s scores', all(vt['values'][c][k] == Ti['scores'][c][dpos[r_]] for c in range(2) for k, r_ in enumerate(vt['rows'])), True)

# ---- the Python shown runs on a CSV export and gives the report's numbers ------------------------------------------------------------
work = tempfile.mkdtemp()
dfx = pd.DataFrame({'comment': [t if t is not None else '' for t in texts], 'g': groups, 'customer': cust_vals, 'num': np.arange(400.0)})
dfx.loc[7, 'comment'] = 'NA'           # read as text, not as a missing value
dfx.loc[8, 'comment'] = 'None, null'
tid2 = table({'comment': [None if t == '' else t for t in dfx['comment']], 'g': groups, 'customer': cust_vals, 'num': np.arange(400.0)})
dfx.to_csv(os.path.join(work, 'Comments.csv'), index=False)
DUMP = '''
import json as _j
_o = {}
for _k in ("summary", "term_list", "phrase_list", "singular_values", "docs", "terms", "loadings", "scores", "dtm", "chosen"):
    if _k in globals():
        _v = globals()[_k]
        _o[_k] = _v.to_dict("split") if hasattr(_v, "to_dict") and not isinstance(_v, dict) else (_v.tolist() if hasattr(_v, "tolist") else _v)
print("@@" + _j.dumps(_o, default=float))
'''


def run(code):
    p_ = subprocess.run([sys.executable, '-c', code + DUMP], cwd=work, capture_output=True, text=True, timeout=600)
    if p_.returncode:
        print(p_.stderr[-3000:])
        return None
    return json.loads(next(ln for ln in p_.stdout.splitlines() if ln.startswith('@@'))[2:])


EXPLORES = [({}, None), ({'stemming': 'combine', 'recodes': {'cheap': 'price'}, 'stop_add': ['value']}, None), ({'stemming': 'all', 'phrases': [want[0]], 'tokenizing': 'basic'}, None),
            ({'id_col': 'customer', 'regex': r"[a-z]{3,}"}, None), ({}, list(range(0, 400, 2))), ({'max_words': 3, 'max_phrases': 25, 'min_chars': 3}, list(range(50, 400)))]
for kw, rows in EXPLORES:
    r = call('text.explore', table=tid2, column='comment', rows=rows, table_name='Comments', **kw)
    o = run(r['code'])
    label = f'{kw or "defaults"}{" with a row list" if rows else ""}'
    if not check(f'the Summary and lists code runs ({label})', o is not None, True):
        continue
    s_ = o['summary']
    check(f'it gives the Summary Counts ({label})', [s_['Number of Terms'], s_['Number of Cases'], s_['Total Tokens'], round(s_['Tokens per Case'], 12), round(s_['Portion Non-empty'], 12)],
          [r['summary'][k] for k in ('terms', 'cases', 'tokens')] + [round(r['summary']['tokens_per_case'], 12), round(r['summary']['portion_nonempty'], 12)])
    check(f'the Term List ({label})', o['term_list']['data'], [[x['term'], x['count']] for x in r['terms']])
    check(f'the Phrase List ({label})', o['phrase_list']['data'], [[x['phrase'], x['count'], x['n']] for x in r['phrases']])
check('NA and None in the text are words, not missing values', any(x['term'] == 'na' for x in call('text.explore', table=tid2, column='comment')['terms']), True)
for kw in ({'centering': 'centered'}, {'centering': 'uncentered', 'weighting': 'logfreq'}, {'centering': 'scaled', 'weighting': 'ternary', 'stemming': 'combine'}, {'id_col': 'customer', 'weighting': 'binary'}):
    r = call('text.lsa', table=tid2, column='comment', min_freq=2, max_terms=80, k=6, show=6, seed=5, table_name='Comments', **kw)
    o = run(r['code'])
    if not check(f'the LSA code runs ({kw})', o is not None, True):
        continue
    check(f'it chooses the report\'s terms ({kw})', o['chosen'], r['terms'])
    sv = o['singular_values']['data']
    check.near(f'and gives its singular values, percents and vectors ({kw})', max(mx([x[1] for x in sv], [x['value'] for x in r['singular']]), mx([x[2] for x in sv], [x['percent'] for x in r['singular']]),
                                                                              mx(np.array(o['docs']).T, r['docs']), mx(np.array(o['terms']).T, r['term_vectors'])), 0.0, abs_=1e-12)
for kw in ({'method': 'varimax'}, {'method': 'nmf', 'weighting': 'frequency'}, {'method': 'lda'}, {'method': 'varimax', 'centering': 'uncentered', 'id_col': 'customer'}):
    with contextlib.redirect_stdout(io.StringIO()):
        r = call('text.topics', table=tid2, column='comment', n_topics=3, min_freq=2, max_terms=60, seed=7, scores=3, table_name='Comments', **kw)
    o = run(r['code'])
    if not check(f'the Topic Analysis code runs ({kw})', o is not None, True):
        continue
    check.near(f'it gives the report\'s loadings and scores ({kw})', max(mx(np.array(o['loadings']['data']).T, r['loadings']), mx(np.array(o['scores']).T, r['scores'])), 0.0, abs_=1e-12)
    check(f'and its top terms ({kw})', o['loadings']['index'], r['terms'])
for kw in ({'weighting': 'binary', 'max_terms': 12}, {'weighting': 'tfidf', 'terms': [order[3], order[1]]}):
    r = call('text.dtm', table=tid2, column='comment', table_name='Comments', rows=list(range(100, 400)), **kw)
    o = run(r['code'])
    if not check(f'the Save Document Term Matrix code runs ({kw})', o is not None, True):
        continue
    check(f'it gives the saved values ({kw})', (o['dtm']['columns'], mx(np.array(o['dtm']['data']).T, r['values'])), (r['terms'], 0.0))

# ---- the defaults on 5,000 rows -------------------------------------------------------------------------------------------------------------------------
big = [''.join(sentence(rng) for _ in range(rng.integers(1, 4))) for _ in range(5000)]
tb = table({'comment': big})
t0 = time.time()
rb = call('text.explore', table=tb, column='comment')
t1 = time.time()
lb = call('text.lsa', table=tb, column='comment')
t2 = time.time()
tp_ = call('text.topics', table=tb, column='comment')
t3 = time.time()
print(f'      5,000 rows natively: explore {t1 - t0:.2f} s, LSA {t2 - t1:.2f} s ({lb["n_terms"]} terms, {lb["k"]} vectors), topics {t3 - t2:.2f} s; '
      f'the explore result {len(json.dumps(rb)) / 1e6:.2f} MB')
check('5,000 rows: the Summary and lists, LSA and topics each in under 2 s natively', (t1 - t0 < 2, t2 - t1 < 2, t3 - t2 < 2), (True, True, True))

sys.exit(check.done())
