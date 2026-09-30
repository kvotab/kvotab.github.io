#!/usr/bin/env python3
"""Analyze > Text Explorer's backend (resources/py/smui/text.py), checked
against Porter's (1980) paper (every example of every step, the measure m,
the consonants, the two worked examples), the Snowball English (Porter2)
definition's own cases and the snowballstemmer package on some 235,000
words (Python's docs and the system word list; skipped without the
package), scikit-learn's ENGLISH_STOP_WORDS and CountVectorizer called
directly, counts made here another way (tokens, terms, phrases in JMP's
order, the rows of each, the summary), the recodes in JMP's place (before
the length check, the phrases, the stop words and the stemming; a stemmed
form's recode on each word of the stem; one pass), JMP's documented weightings (TF IDF
and Log Freq with log10) computed by formula on a dense matrix, numpy's SVD
of that matrix (every centering) and the eigenvalues of its correlation and
covariance matrices, statsmodels' varimax (factor_rotation.rotate_factors)
and the varimax criterion, the top loadings in JMP's order (by absolute value), scikit-learn's NMF and LatentDirichletAllocation
called directly; Latent Class Analysis on planted classes (the likelihood,
the posteriors and the EM fixed point computed densely, EM from the truth,
JMP's top-term score, the Kullback-Leibler distances and their map against
Multidimensional Scaling's), Cluster Terms and Documents against scipy's
Ward linkage and fcluster, Term Selection against scikit-learn's ElasticNet
fitted anew, the lasso's KKT conditions, statsmodels' elastic net (the
objective) and its Wald tests, Sentiment Analysis against VADER called
directly (skipped without vaderSentiment); and by running the Python shown
under each result on a CSV export of the table. It also times the defaults
on 5,000 rows.

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
want = sorted((p for p in pc if pc[p] > 1), key=lambda p: (-pc[p], -len(p.split()), p))   # JMP's order: count, then the longer, then alphabetically
check('the Phrase List: 2 to 4 words, not beginning or ending with a stop word, seen twice, as counted here, in JMP\'s order', [(x['phrase'], x['count'], x['n']) for x in res['phrases']],
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
check('and no phrase begins or ends with it', [(x['phrase'], x['count']) for x in ru['phrases']][:50], [(p, pu[p]) for p in sorted((p for p in pu if pu[p] > 1), key=lambda p: (-pu[p], -len(p.split()), p))][:50])
rc = call('text.explore', table=tid, column='comment', recodes={top2: top1})
check('Recode: the two terms count as one', {x['term']: x['count'] for x in rc['terms']}.get(top1), cnt[top1] + cnt[top2])
check('and the recoded term lists its words, its own too (for Show Text)', sorted(w for w, _ in rc['forms'][top1]), sorted([top1, top2]))
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
check('Snowball the same: deliveries -> deliveri, delivered -> deliv, delivery -> deliveri', [TX.SnowballStemmer().stem(w) for w in ('deliveries', 'delivered', 'delivery')], ['deliveri', 'deliv', 'deliveri'])
check('so deliveries and delivery combine', cs.get('deliveri' + DOT), 2)
ca = {x['term']: x['count'] for x in ra_['terms']}
check('Stem All Terms: every word of three or more letters a-z is stemmed', all(t.endswith(DOT) for t in ca), True)
SN = TX.SnowballStemmer()
check('the stem of every word (Snowball\'s, the default), counted', ca, dict(collections.Counter(SN.stem(w) + DOT for t in st_texts for w in ref_tokens(t) if w not in STOP)))
rp_ = call('text.explore', table=tst, column='t', stemming='all', stemmer='porter')
check('Stemmer: Porter (1980): Porter\'s stem of every word, counted', {x['term']: x['count'] for x in rp_['terms']}, dict(collections.Counter(P.stem(w) + DOT for t in st_texts for w in ref_tokens(t) if w not in STOP)))
check('the total count is unchanged by stemming', (rn['summary']['tokens'], rs['summary']['tokens'], ra_['summary']['tokens']), (rn['summary']['tokens'],) * 3)
stem_rep = {x['stem']: x['forms'] for x in rs['stems']}
check('the Stem Report: the words of each stem, with their counts', stem_rep['return' + DOT], [['return', 1], ['returned', 1], ['returning', 1], ['returns', 1]])
check('and Show Text\'s words for a stemmed term', sorted(w for w, _ in rs['forms']['crash' + DOT]), ['crashed', 'crashes', 'crashing'])
rsu = call('text.explore', table=tst, column='t', stemming='combine', stop_add=['crash' + DOT])
check('a stemmed term as a stop word drops all its words', any(x['term'].startswith('crash') for x in rsu['terms']), False)

# ---- recoding comes before the stop words and the stemming, as in JMP (its help's text processing steps) ---------------------------------------------------
rt_ = table({'t': ['the parcel arrived', 'a parcel arrived late', 'two packages arrived', 'the package was lost', 'I returned it, returning it again',
                   'returns are free', 'my refund', 'refunds take a week', 'an extraordinary thing', 'ok']})
def terms_of(**kw):
    return {x['term']: x['count'] for x in call('text.explore', table=rt_, column='t', **kw)['terms']}
check('a recode reaches the stemmer: parcel -> package counts the parcels as packages, which stem with them (packag· 4)',
      (terms_of(stemming='combine', recodes={'parcel': 'package'}).get('packag' + DOT), 'parcel' in terms_of(stemming='combine', recodes={'parcel': 'package'})), (4, False))
check('... where after the stemming it would have made a term of its own (the old order: packag· 2 and package 2)', (terms_of(stemming='combine').get('packag' + DOT), terms_of(stemming='combine').get('parcel')), (2, 2))
rs2 = terms_of(stemming='combine', recodes={'return' + DOT: 'refund'})
check('a recode of a stemmed form recodes each word of the stem (returned, returning, returns), then they stem with refund and refunds (refund· 5)', (rs2.get('refund' + DOT), 'return' + DOT in rs2), (5, False))
rs3 = terms_of(stemming='combine', recodes={'return' + DOT: 'refund', 'returned': 'shipped'})
check('... a word\'s own recode wins over its stem\'s', (rs3.get('refund' + DOT), rs3.get('shipped')), (4, 1))
check('... and it recodes the words of the stem even with No Stemming (refunds its own term then)', (terms_of(recodes={'return' + DOT: 'refund'}).get('refund'), terms_of(recodes={'return' + DOT: 'refund'}).get('refunds')), (4, 1))
rs4 = terms_of(recodes={'parcel': 'package', 'package': 'box'})
check('the recodes are one pass: parcel -> package -> box stops at package', (rs4.get('package'), rs4.get('box')), (2, 1))
check('a word recoded to nothing is dropped, and one recoded to a stop word too', (terms_of(recodes={'parcel': ''}).get('parcel'), terms_of(recodes={'parcel': 'the'}).get('parcel')), (None, None))
check('a stop word recoded to a word becomes a term (the stop words are checked after the recodes)', terms_of(recodes={'the': 'this one'}).get('this one'), 2)
check('the lengths are checked after the recode: a long word recoded short is kept, a short one recoded long is not',
      (terms_of(max_chars=7, recodes={'extraordinary': 'odd'}).get('odd'), terms_of(max_chars=7, recodes={'ok': 'okayokay'}).get('okayokay')), (1, None))
ph_ = call('text.explore', table=rt_, column='t', recodes={'parcel': 'package'})
check('the Phrase List counts the recoded words: "package arrived" twice, no "parcel arrived"', ({x['phrase']: x['count'] for x in ph_['phrases']}.get('package arrived'), any('parcel' in x['phrase'] for x in ph_['phrases'])), (2, False))
check('a recode of an added phrase applies to the joined phrase', terms_of(phrases=['parcel arrived'], recodes={'parcel arrived': 'delivered'}).get('delivered'), 2)
fr_ = call('text.explore', table=rt_, column='t', stemming='combine', recodes={'parcel': 'package'})['forms']
check('Show Text\'s words of a term: the words in the texts, the recoded ones too', sorted(w for w, _ in fr_['packag' + DOT]), ['package', 'packages', 'parcel'])

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
# JMP's help (Text Explorer > Save Options): Log Freq log10(1 + x), TF IDF TF * log10(nDoc / nDocTerm)
REF_W = {'binary': (C > 0) * 1.0, 'ternary': np.where(C > 1, 2.0, np.where(C > 0, 1.0, 0.0)), 'frequency': C,
         'logfreq': np.log10(1 + C), 'tfidf': C * np.log10(400 / nd)}
for w, M in REF_W.items():
    d = call('text.dtm', table=tid, column='comment', weighting=w, min_freq=2, max_terms=60)
    check(f'Save Document Term Matrix, {TX.WEIGHTINGS[w]}: the formula\'s values', (d['terms'] == chosen, mx(np.array(d['values']).T, M) < 1e-12), (True, True))
dn = np.array(call('text.dtm', table=tid, column='comment', weighting='tfidf', min_freq=2, max_terms=60)['values']).T
check.near('TF IDF takes the base-10 log: the natural-log values are ln 10 = 2.3026 times these', float(np.sum(C * np.log(400 / nd)) / np.sum(dn)), math.log(10), rel=1e-12)
one = call('text.dtm', table=table({'t': ['apple pear', 'apple', 'plum', 'kiwi', 'fig', 'lime', 'date', 'nut', 'yam', 'oat']}), column='t', weighting='tfidf', terms=['apple', 'pear'])
check.near('TF IDF by hand: a term once in 1 of 10 documents is 1 × log10(10 / 1) = 1', one['values'][1][0], 1.0, rel=1e-15)
check.near('... and once in 2 of 10, log10(10 / 2)', one['values'][0][0], math.log10(5), rel=1e-15)
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
check('JMP\'s defaults: TF IDF, Centered and Scaled; terms seen 4 or more times', (Ld['weighting'], Ld['centering'], Ld['n_terms']), ('tfidf', 'scaled', sum(1 for w in cnt if cnt[w] >= 4)))
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
Tp = call('text.topics', table=tid, column='comment', n_topics=4, min_freq=2, max_terms=60, top=5, scores=4, seed=3, centering='centered')
check('Topic Analysis\'s default centering is JMP\'s too: Centered and Scaled', call('text.topics', table=tid, column='comment', n_topics=2, min_freq=2)['centering'], 'scaled')
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
check('Top Loadings by Topic: the terms with the largest loadings in absolute value, the largest first (JMP\'s order)', [[x['term'] for x in tp] for tp in Tp['top']],
      [[chosen[j] for j in np.argsort(-np.abs(load[:, t]), kind='stable')[:5]] for t in range(4)])
Tp10 = call('text.topics', table=tid, column='comment', n_topics=4, min_freq=2, max_terms=60, top=20, seed=3, centering='centered')
absl = [[abs(x['loading']) for x in tp] for tp in Tp10['top']]
check('... so each topic\'s list falls in absolute value, and holds negative loadings among its largest', (all(a == sorted(a, reverse=True) for a in absl), any(x['loading'] < 0 for tp in Tp10['top'] for x in tp)), (True, True))
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
for _k in ("summary", "term_list", "phrase_list", "singular_values", "docs", "terms", "loadings", "scores", "dtm", "chosen", "top_terms"):
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
            ({'stemming': 'combine', 'recodes': {'deliveri\u00b7': 'shipping', 'late': '', want[0]: 'combo', 'slow': 'crashed'}, 'phrases': [want[0]], 'max_chars': 7}, None),
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
    check.near(f'and gives its singular values, eigenvalues, percents and vectors ({kw})', max(mx([x[1] for x in sv], [x['value'] for x in r['singular']]), mx([x[2] for x in sv], [x['eigen'] for x in r['singular']]), mx([x[3] for x in sv], [x['percent'] for x in r['singular']]),
                                                                              mx(np.array(o['docs']).T, r['docs']), mx(np.array(o['terms']).T, r['term_vectors'])), 0.0, abs_=1e-12)
for kw in ({'method': 'varimax'}, {'method': 'nmf', 'weighting': 'frequency'}, {'method': 'lda'}, {'method': 'varimax', 'centering': 'uncentered', 'id_col': 'customer'}):
    with contextlib.redirect_stdout(io.StringIO()):
        r = call('text.topics', table=tid2, column='comment', n_topics=3, min_freq=2, max_terms=60, seed=7, scores=3, table_name='Comments', **kw)
    o = run(r['code'])
    if not check(f'the Topic Analysis code runs ({kw})', o is not None, True):
        continue
    check.near(f'it gives the report\'s loadings and scores ({kw})', max(mx(np.array(o['loadings']['data']).T, r['loadings']), mx(np.array(o['scores']).T, r['scores'])), 0.0, abs_=1e-12)
    check(f'and its terms ({kw})', o['loadings']['index'], r['terms'])
    check(f'and its Top Loadings by Topic, by the absolute loading ({kw})', o['top_terms'], [[x['term'] for x in tp] for tp in r['top']])
for kw in ({'weighting': 'binary', 'max_terms': 12}, {'weighting': 'tfidf', 'terms': [order[3], order[1]]}):
    r = call('text.dtm', table=tid2, column='comment', table_name='Comments', rows=list(range(100, 400)), **kw)
    o = run(r['code'])
    if not check(f'the Save Document Term Matrix code runs ({kw})', o is not None, True):
        continue
    check(f'it gives the saved values ({kw})', (o['dtm']['columns'], mx(np.array(o['dtm']['data']).T, r['values'])), (r['terms'], 0.0))

# ---- the graphs' code: the singular values' bars and the topic scores whole; the lines the word cloud's and the SVD plots'
# code start with (the page adds its layout and drawing: test-ui-text.py runs those blocks in the page); By groups
from test_charts import run_snippet  # noqa: E402

frame_c = pd.read_csv(os.path.join(work, 'Comments.csv'), dtype=str, keep_default_na=False)   # the CSV as written, written again the same


def fig_of(code, label):
    figs, err = run_snippet(code, frame_c, 'Comments', work)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1], 'plt.show()')
    return figs[0] if figs else None


for kw in ({}, {'centering': 'uncentered', 'weighting': 'logfreq', 'k': 40}, {'id_col': 'customer', 'k': 20}):
    r = call('text.lsa', table=tid2, column='comment', min_freq=2, max_terms=80, show=2, seed=5, table_name='Comments', **{'k': 6, **kw})
    F = fig_of(r['plot_code']['singular'], f'the singular values\' bars ({kw})')
    if F:
        ax = F['axes'][0]
        top = r['singular'][:30]
        check.near(f'the singular values\' bars: the percents of the first {len(top)} ({kw})', mx([b['w'] for b in ax['bars']], [x['percent'] for x in top]), 0.0, abs_=1e-12)
        check.near(f'... each at its number, the first at the top ({kw})', mx([b['y'] + b['h'] / 2 for b in ax['bars']], [x['number'] for x in top]), 0.0, abs_=1e-12)
        check(f'... the titles and the size ({kw})', (ax['yinverted'], ax['xlabel'], ax['title'], F['size']), (True, 'Percent', 'Singular values, percent', [2.8, max(140, 13 * len(top) + 50) / 100]))
    o = run(r['svd_head'].replace('import matplotlib.pyplot as plt\n', ''))
    if check(f'the SVD plots\' lines run ({kw})', o is not None, True):
        check.near(f'... and give the documents\' and the terms\' coordinates ({kw})', max(mx(np.array(o['docs'])[:, :2].T, r['docs']), mx(np.array(o['terms'])[:, :2].T, r['term_vectors'])), 0.0, abs_=1e-12)
        check(f'... and the terms in the report\'s order ({kw})', o['chosen'], r['terms'])
for kw in ({'method': 'varimax'}, {'method': 'nmf', 'weighting': 'frequency'}, {'method': 'lda'}, {'method': 'varimax', 'id_col': 'customer'}):
    with contextlib.redirect_stdout(io.StringIO()):
        r = call('text.topics', table=tid2, column='comment', n_topics=3, min_freq=2, max_terms=60, seed=7, scores=2, table_name='Comments', **kw)
    F = fig_of(r['plot_code']['scores'], f'the topic scores ({kw})')
    if F:
        ax = F['axes'][0]
        pts = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check.near(f'the topic scores: each document\'s scores on the first two topics ({kw})', mx(np.array(pts).T, r['scores']) if len(pts) == len(r['scores'][0]) else 1e9, 0.0, abs_=1e-12)
        tops = [', '.join(x['term'] for x in r['top'][t][:3]) for t in (0, 1)]
        check(f'... the topics\' three largest terms on the axes, the title and the size ({kw})', (ax['xlabel'], ax['ylabel'], ax['title'], F['size']),
              (f'Topic 1 ({tops[0]})', f'Topic 2 ({tops[1]})', 'Topic scores of comment', [4.4, 3.6]))
with contextlib.redirect_stdout(io.StringIO()):
    r1 = call('text.topics', table=tid2, column='comment', n_topics=1, min_freq=2, max_terms=60, seed=7, table_name='Comments')
check('one topic: no topic scores plot', r1['plot_code'], {})
for kw in ({}, {'id_col': 'customer', 'stemming': 'combine'}):
    r = call('text.explore', table=tid2, column='comment', table_name='Comments', **kw)
    o = run(r['cloud_head'].replace('import matplotlib.pyplot as plt\n', ''))
    if check(f'the word cloud\'s lines run ({kw})', o is not None, True):
        check(f'... and give the Term List the cloud takes its words from ({kw})', o['term_list']['data'], [[x['term'], x['count']] for x in r['terms']])
    check(f'... and keep every row of the report before the rows without an ID ({kw})', 'every = df' in r['cloud_head'], bool(kw))
# a By group (its where line) with rows left out: the code of every result keeps the group and drops the rows
grp_rows = [i for i in range(400) if groups[i] == groups[0] and i not in (0, 5)]
where = [{'column': 'g', 'value': groups[0]}]
dropped = [i for i in (0, 5) if groups[i] == groups[0]]
r = call('text.explore', table=tid2, column='comment', rows=grp_rows, where=where, table_name='Comments')
L_ = call('text.lsa', table=tid2, column='comment', rows=grp_rows, where=where, min_freq=2, max_terms=60, k=4, show=2, seed=5, table_name='Comments')
with contextlib.redirect_stdout(io.StringIO()):
    T_ = call('text.topics', table=tid2, column='comment', rows=grp_rows, where=where, n_topics=3, min_freq=2, max_terms=60, seed=7, table_name='Comments')
codes = [r['code'], r['cloud_head'], L_['code'], L_['svd_head'], L_['plot_code']['singular'], T_['code'], T_['plot_code']['scores']]
check('a By group: every code keeps its rows and drops the ones left out', all(f'df = df[df["g"] == {json.dumps(groups[0])}]' in c and f'df = df.drop(index={dropped})' in c for c in codes), True)
o = run(r['code'])
if check('a By group: the Summary and lists code runs', o is not None, True):
    check('... and gives the group\'s Term List', o['term_list']['data'], [[x['term'], x['count']] for x in r['terms']])
F = fig_of(T_['plot_code']['scores'], 'a By group: the topic scores')
if F:
    pts = F['axes'][0]['scatter'][0]['xy']
    check.near('... on the group\'s documents', mx(np.array(pts).T, T_['scores']) if len(pts) == len(T_['scores'][0]) else 1e9, 0.0, abs_=1e-12)

# ---- Snowball's English stemmer (Porter2): the definition's own cases, and the snowballstemmer package on a large vocabulary ----------------
SN = TX.SnowballStemmer()
cases = {'skies': 'sky', 'skis': 'ski', 'dying': 'die', 'lying': 'lie', 'tying': 'tie', 'news': 'news', 'howe': 'howe', 'atlas': 'atlas', 'only': 'onli',
         'ties': 'tie', 'cries': 'cri', 'gas': 'gas', 'this': 'this', 'gaps': 'gap', 'kiwis': 'kiwi', 'herrings': 'herring', 'proceed': 'proceed',
         'hopping': 'hop', 'hoped': 'hope', 'generate': 'generat', 'generously': 'generous', 'communism': 'communism', 'cry': 'cri', 'by': 'by', 'say': 'say'}
check('Porter2 by its definition: exceptional forms, the ies/ied rule, s after a vowel, the step 1a exceptions, undoubling, the short word, gener/commun, y',
      {w: SN.stem(w) for w in cases}, cases)
check('Porter2 marks y after a vowel as a consonant (enjoying, employ)', (SN.stem('enjoying'), SN.stem('employ'), SN.stem('toys')), ('enjoy', 'employ', 'toy'))
def snowball2():
    """The English stemmer of the snowballstemmer package as Snowball 1 and 2
    define it (the algorithm ported here): the installed package when it is
    a 2.x, else version 2.2.0 fetched into local/ (git-ignored; Snowball 3.0
    of 2025 revised the English algorithm). None without either."""
    import importlib.metadata as md
    import importlib.util
    try:
        import snowballstemmer
        if md.version('snowballstemmer').startswith('2.'):
            return snowballstemmer.stemmer('english'), md.version('snowballstemmer')
    except ImportError:
        pass
    where = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local', 'snowball2')
    pkg = os.path.join(where, 'snowballstemmer')
    if not os.path.exists(os.path.join(pkg, '__init__.py')):
        import zipfile
        tmp = tempfile.mkdtemp()
        got = subprocess.run([sys.executable, '-m', 'pip', 'download', 'snowballstemmer==2.2.0', '--no-deps', '-d', tmp], capture_output=True, text=True)
        whl = [f for f in os.listdir(tmp) if f.endswith('.whl')] if got.returncode == 0 else []
        if not whl:
            return None, None
        zipfile.ZipFile(os.path.join(tmp, whl[0])).extractall(where)
    spec = importlib.util.spec_from_file_location('snowball2', os.path.join(pkg, '__init__.py'), submodule_search_locations=[pkg])
    mod = importlib.util.module_from_spec(spec)
    sys.modules['snowball2'] = mod
    spec.loader.exec_module(mod)
    return mod.stemmer('english'), '2.2.0'


ref, ref_version = snowball2()
if ref is None:
    print('      (snowballstemmer 2 is not installed and could not be fetched: its check skipped)')
else:
    from pydoc_data.topics import topics as _topics
    voc = set(re.findall(r'[a-z]+', ' '.join(_topics.values()).lower())) | set(cases)
    if os.path.exists('/usr/share/dict/words'):
        voc |= {w.strip().lower() for w in open('/usr/share/dict/words') if w.strip().isalpha() and w.strip().isascii()}
    bad = [w for w in sorted(voc) if SN.stem(w) != ref.stemWord(w)]
    check(f'Porter2 = the snowballstemmer package {ref_version} (Snowball 2) on {len(voc)} words (Python\'s own docs and the system word list)', bad[:10], [])
check('the code under a stemmed report holds the Snowball stemmer (and not Porter\'s)', ('class SnowballStemmer' in rs['code'], 'class PorterStemmer' in rs['code']), (True, False))
check('... and Porter\'s with Stemmer: Porter', 'class PorterStemmer' in call('text.explore', table=tst, column='t', stemming='combine', stemmer='porter')['code'], True)
check('an unknown stemmer: an error', 'stemmer' in call('text.explore', table=tst, column='t', stemming='all', stemmer='lovins')['error'], True)
check('JMP\'s launch defaults: 5000 phrases, words of 1 to 50 characters', (res['settings']['max_phrases'], res['settings']['min_chars'], res['settings']['max_chars']), (5000, 1, 50))

# ---- the singular values' eigenvalues: those of the correlation (scaled) or covariance (centered) matrix ---------------------------------------------
for centering, ref_m in (('scaled', np.corrcoef(M, rowvar=False)), ('centered', np.cov(M, rowvar=False))):
    L = call('text.lsa', table=tid, column='comment', weighting='tfidf', centering=centering, min_freq=2, max_terms=60, k=8, seed=3)
    ev = np.sort(np.linalg.eigvalsh(ref_m))[::-1][:8]
    check.near(f'Eigenvalue, {TX.CENTERING[centering]}: numpy\'s eigenvalues of the {"correlation" if centering == "scaled" else "covariance"} matrix of the weighted DTM', mx([x['eigen'] for x in L['singular']], ev), 0.0, abs_=1e-9 * ev[0])
La = call('text.lsa', table=tid, column='comment', centering='scaled', min_freq=2, max_terms=60, k=1000)
check.near('Centered and Scaled: the eigenvalues (all but the smallest: k is the terms less one) and the smallest sum to the number of terms',
           sum(x['eigen'] for x in La['singular']) + float(np.min(np.linalg.eigvalsh(np.corrcoef(M, rowvar=False)))), float(La['n_terms']), rel=1e-9)
Lu = call('text.lsa', table=tid, column='comment', centering='uncentered', min_freq=2, max_terms=60, k=5)
check.near('Uncentered: s² / n', mx([x['eigen'] for x in Lu['singular']], [x['value'] ** 2 / 400 for x in Lu['singular']]), 0.0, abs_=1e-12)

# ---- Latent Class Analysis: a Bernoulli mixture with planted classes ----------------------------------------------------------------------------------------
lrng = np.random.default_rng(77)
LW = ['alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel', 'india', 'juliet', 'kilo', 'lima', 'mike', 'november', 'oscar', 'papa']
TRUE_P = np.full((3, 16), 0.05)
TRUE_P[0, :5], TRUE_P[1, 5:10], TRUE_P[2, 10:15] = 0.7, 0.6, 0.65
TRUE_P[:, 15] = 0.4
cls = lrng.choice(3, size=600, p=[0.5, 0.3, 0.2])
held = lrng.random((600, 16)) < TRUE_P[cls]
ltexts = [' '.join(LW[j] for j in np.flatnonzero(h)) for h in held]
tl = table({'t': ltexts, 'g': [f'd{i // 2}' for i in range(600)]})
R_ = call('text.lca', table=tl, column='t', n_clusters=3, min_freq=1, seed=11)
from sklearn.metrics import adjusted_rand_score  # noqa: E402
check('LCA: the planted classes found (adjusted Rand index of the most likely cluster)', adjusted_rand_score(cls, np.array(R_['likely'])) > 0.9, True)
Xb = np.array([[1.0 if w in t.split() else 0.0 for w in R_['terms']] for t in ltexts])
pi_, P_ = np.array(R_['pi']), np.array(R_['P']).T
Ld_ = np.log(pi_) + Xb @ np.log(P_) + (1 - Xb) @ np.log1p(-P_)   # dense, term by term
from scipy.special import logsumexp  # noqa: E402
check.near('LCA: the log-likelihood, computed densely from the mixing and term probabilities', R_['loglik'], float(logsumexp(Ld_, axis=1).sum()), rel=1e-10)
Rd = np.exp(Ld_ - logsumexp(Ld_, axis=1)[:, None])
check.near('LCA: each document\'s cluster probabilities are its posterior probabilities', mx(R_['R'], Rd), 0.0, abs_=1e-10)
Nc = Rd.sum(axis=0)
check.near('LCA: the EM fixed point: one more step leaves the term probabilities (with the 0.01 prior) and the mixing probabilities as they are',
           max(mx((Xb.T @ Rd + 0.01) / (Nc + 0.02), P_), mx(Nc / 600, pi_)), 0.0, abs_=1e-6)
check.near('LCA: BIC = -2 log L + (k - 1 + k m) log n', R_['bic'], -2 * R_['loglik'] + (2 + 3 * P_.shape[0]) * math.log(600), rel=1e-12)
check('LCA: the clusters largest first', list(pi_) == sorted(pi_, reverse=True), True)
# an EM from the truth reaches no higher: the five random starts found the maximum
Pt, pit = TRUE_P[:, [LW.index(w) for w in R_['terms']]].T, np.array([0.5, 0.3, 0.2])
for _ in range(2000):
    Lt = np.log(pit) + Xb @ np.log(Pt) + (1 - Xb) @ np.log1p(-Pt)
    Rt = np.exp(Lt - logsumexp(Lt, axis=1)[:, None])
    Nt = Rt.sum(axis=0)
    pit, Pt = Nt / 600, (Xb.T @ Rt + 0.01) / (Nt + 0.02)
Lt = np.log(pit) + Xb @ np.log(Pt) + (1 - Xb) @ np.log1p(-Pt)
check('LCA: the best of five random starts is as good as EM started from the truth', R_['loglik'] >= float(logsumexp(Lt, axis=1).sum()) - 1e-6, True)
mean_ = P_.mean(axis=1, keepdims=True)
S_ = 100 * mean_ * np.log10(P_ / mean_)
check('Top Terms by Cluster: the highest 100 mean(p) log10(p_c / mean(p)), JMP\'s score', [[x['term'] for x in tp] for tp in R_['top']], [[R_['terms'][j] for j in np.argsort(-S_[:, c], kind='stable')[:10]] for c in range(3)])
check.near('... and the scores', mx([[x['score'] for x in tp] for tp in R_['top']], [[S_[j, c] for j in np.argsort(-S_[:, c], kind='stable')[:10]] for c in range(3)]), 0.0, abs_=1e-9)
check('Cluster Most Characteristic (the largest p) and Most Probable (the largest pi p)', (R_['characteristic'], R_['probable']), ((P_.argmax(axis=1) + 1).tolist(), ((P_ * pi_).argmax(axis=1) + 1).tolist()))
q_ = P_ / P_.sum(axis=0)
KL = np.array([[float(np.sum((q_[:, a] - q_[:, b]) * np.log(q_[:, a] / q_[:, b]))) for b in range(3)] for a in range(3)])
check.near('the MDS Plot\'s distances: the symmetric Kullback-Leibler distances between the clusters\' term distributions', mx(R_['kl'], KL), 0.0, abs_=1e-12)
tk = table({f'k{c}': KL[:, c].tolist() for c in range(3)})
Mds = call('mds.fit', table=tk, columns=['k0', 'k1', 'k2'], matrix=True)
got_c = np.array(R_['coords'])
ref_c = np.array(Mds['coords'])[:, :2]
check.near('... mapped as Multidimensional Scaling maps a distance matrix (classical scaling, the signs aside)', mx(np.abs(got_c), np.abs(ref_c)), 0.0, abs_=1e-9)
R2_ = call('text.lca', table=tl, column='t', n_clusters=3, min_freq=1, seed=11)
check('LCA: the same seed, the same clusters', R2_['likely'], R_['likely'])
check('LCA: too few documents for the clusters, and a bad number: errors', ('documents' in call('text.lca', table=table({'t': ['a b', 'b c']}), column='t', n_clusters=3, min_freq=1)['error'],
      'Number of Clusters' in call('text.lca', table=tl, column='t', n_clusters=1)['error']), (True, True))
Rid = call('text.lca', table=tl, column='t', id_col='g', n_clusters=3, min_freq=1, seed=11)
Sv = call('text.lca_save', table=tl, column='t', id_col='g', n_clusters=3, min_freq=1, seed=11)
pos_ = {r_: d for d, rs_ in enumerate(Rid['doc_rows']) for r_ in rs_}
check('Save Probabilities with an ID: each row its document\'s probabilities and most likely cluster', (len(Rid['R']), all(Sv['probs'][c][k] == Rid['R'][pos_[r_]][c] and Sv['likely'][k] == Rid['likely'][pos_[r_]] for c in range(3) for k, r_ in enumerate(Sv['rows']))), (300, True))

# ---- Cluster Terms and Cluster Documents: scipy's Ward linkage on the SVD's vectors -------------------------------------------------------------------------------
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage  # noqa: E402
Lk = call('text.lsa', table=tid, column='comment', min_freq=2, max_terms=60, k=8, show=8, seed=3)
for kind, V in (('terms', np.array(Lk['term_vectors']).T), ('docs', np.array(Lk['docs']).T)):
    Cl = call('text.cluster', table=tid, column='comment', kind=kind, min_freq=2, max_terms=60, k=8, seed=3)
    Zr = linkage(V, 'ward')
    check.near(f'Cluster {kind.title()}: the joins\' distances are scipy\'s Ward linkage of the SVD\'s {"V S" if kind == "terms" else "U S"}, squared and halved (JMP\'s)', mx(Cl['heights'], Zr[:, 2] ** 2 / 2), 0.0, abs_=1e-9 * float(Zr[-1, 2] ** 2))
    check(f'Cluster {kind.title()}: the joins and the leaves\' order', (np.array(Cl['merges']).tolist() == Zr[:, :2].astype(int).tolist(), Cl['order'] == leaves_list(Zr).tolist()), (True, True))
    h = Zr[:, 2] ** 2 / 2
    n_ = len(V)
    best, ratio = min(3, n_), -np.inf
    for q in range(2, min(10, n_ - 1) + 1):
        rr_ = h[n_ - q] / h[n_ - q - 1] if h[n_ - q - 1] > 0 else np.inf
        if rr_ > ratio:
            best, ratio = q, rr_
    check(f'Cluster {kind.title()}: the default number, where the joining distance jumps most (2 to 10)', Cl['default_k'], best)
    for k_ in (best, 5):
        c5 = call('text.cluster', table=tid, column='comment', kind=kind, min_freq=2, max_terms=60, k=8, seed=3, n_clusters=k_)
        fc = fcluster(Zr, k_, 'maxclust')
        check(f'Cluster {kind.title()}, {k_} clusters: the partition is scipy\'s fcluster (maxclust)', adjusted_rand_score(fc, c5['labels']), 1.0)
        first = [c5['labels'][leaf] for leaf in leaves_list(Zr)]
        check(f'... numbered in the order of the dendrogram\'s leaves', list(dict.fromkeys(first)), list(range(k_)))
check('Cluster Documents with an ID: a leaf per document, with its rows', (lambda c: (c['n'], sorted(r_ for rs_ in c['doc_rows'] for r_ in rs_) == list(range(400))))(call('text.cluster', table=tid, column='comment', kind='docs', id_col='customer', min_freq=2, k=6)), (len(ids), True))

# ---- Term Selection: the elastic net against scikit-learn and the KKT conditions, the Wald tests against statsmodels --------------------------------------
import scipy.sparse as _sp  # noqa: E402
import statsmodels.api as sm  # noqa: E402
from sklearn.linear_model import ElasticNet  # noqa: E402
srng = np.random.default_rng(31)
SW = ['fast', 'late', 'broken', 'great', 'rude', 'helpful', 'cheap', 'refund', 'lovely', 'awful', 'okay', 'fine', 'box', 'blue', 'red', 'green', 'store', 'online']
effect = {'fast': 0.9, 'great': 1.2, 'helpful': 0.8, 'lovely': 1.0, 'late': -1.0, 'broken': -1.3, 'rude': -0.9, 'awful': -1.1}
held = srng.random((500, len(SW))) < 0.18
score = held @ np.array([effect.get(w, 0.0) for w in SW]) + srng.normal(0, 0.8, 500)
stexts = [' '.join(w for w, h in zip(SW, row) if h) or 'nothing' for row in held]
yb = (score + srng.normal(0, 0.5, 500) > 0).astype(int)
ts_t = table({'t': stexts, 'y': score.tolist(), 'yes': ['yes' if v else 'no' for v in yb], 'rid': [f'r{i}' for i in range(500)]})
for fam, resp, tgt in (('normal', 'y', None), ('binomial', 'yes', 'yes')):
    Ts = call('text.termsel', table=ts_t, column='t', response=resp, target=tgt, min_freq=10)
    if not check(f'Term Selection ({fam}): no error', Ts.get('error'), None):
        continue
    C_ = TX._corpus(ts_t, 't', None, None, TX._config())
    cols_ = TX._chosen(C_, 10, 1000)
    Xw_ = TX.weigh(C_.X[:, cols_], 'binary').toarray()
    yy = score if fam == 'normal' else (np.array(['yes' if v else 'no' for v in yb]) == 'yes').astype(float)
    sd_ = Xw_.std(axis=0, ddof=1)
    Xs_ = Xw_ / sd_
    lam, N_ = Ts['lambda'], 500
    coef = np.zeros(len(cols_))
    names_ = [str(C_.vocab[j]) for j in cols_]
    for x in Ts['terms']:
        coef[names_.index(x['term'])] = x['coef'] * sd_[names_.index(x['term'])]   # on the scaled terms
    if fam == 'normal':
        en = ElasticNet(alpha=lam, l1_ratio=0.99, tol=1e-12, max_iter=1000000).fit(Xs_, yy)
        check.near('Term Selection, normal: at the chosen penalty, scikit-learn\'s ElasticNet fitted anew on the scaled terms', mx(coef, en.coef_), 0.0, abs_=2e-4)
        eta_ = Xs_ @ en.coef_ + en.intercept_
        k_ = int(np.sum(en.coef_ != 0)) + 2
        ll_ = -0.5 * N_ * (math.log(2 * math.pi * np.sum((yy - eta_) ** 2) / N_) + 1)
        check.near('... and its AICc: -2 log L + 2k + 2k(k + 1)/(N - k - 1), k the terms, the intercept and the variance', Ts['aicc'], -2 * ll_ + 2 * k_ + 2 * k_ * (k_ + 1) / (N_ - k_ - 1), rel=1e-6)
    else:
        b0 = Ts['intercept']
        pr_ = 1 / (1 + np.exp(-(Xs_ @ coef + b0)))
        g_ = Xs_.T @ (yy - pr_) / N_
        act = coef != 0
        check.near('Term Selection, binomial: the KKT conditions of -loglik/N + lambda (0.99 |b| + 0.01 b²/2) hold for the kept terms', float(np.max(np.abs(g_[act] - lam * (0.99 * np.sign(coef[act]) + 0.01 * coef[act])))), 0.0, abs_=2e-5)
        check('... and the left-out ones: |gradient| <= 0.99 lambda', bool(np.all(np.abs(g_[~act]) <= 0.99 * lam * (1 + 1e-3))), True)
        check.near('... and the intercept: the residuals sum to 0', float(np.sum(yy - pr_)) / N_, 0.0, abs_=1e-6)
        glm = sm.GLM(yy, sm.add_constant(Xs_), family=sm.families.Binomial()).fit_regularized(method='elastic_net', alpha=np.r_[0.0, np.full(len(cols_), lam)], L1_wt=0.99, cnvrg_tol=1e-12, maxiter=5000)
        pen = lambda c0, c: -np.mean(yy * (Xs_ @ c + c0) - np.logaddexp(0, Xs_ @ c + c0)) + lam * (0.99 * np.sum(np.abs(c)) + 0.005 * np.sum(c ** 2))   # noqa: E731
        check('... and its objective is no higher than statsmodels\' elastic net\'s (GLM fit_regularized, which stops short here)', pen(b0, coef) <= pen(glm.params[0], np.asarray(glm.params[1:])) + 1e-12, True)
    path = Ts['path']
    a_ = [x['aicc'] for x in path]
    best_ = int(np.argmin(a_))
    check(f'Term Selection ({fam}): the kept step has the smallest AICc on the path', Ts['best_step'], best_)
    stop = next((l for l in range(len(a_)) if l - int(np.argmin(a_[:l + 1])) >= 10 and path[l]['nonzero'] >= 4), None)
    check(f'... and early stopping ended the path 10 penalties after the best (with 4 terms or more in)', (stop, len(path) - 1) if stop is not None else (len(path), 150), (len(path) - 1, len(path) - 1) if stop is not None else (150, 150))
    planted = {w for w, e in effect.items()}
    top_ = {x['term'] for x in sorted(Ts['terms'], key=lambda x: -abs(x['coef']))[:8]}
    check(f'... the eight planted terms have the eight largest coefficients ({fam})', top_, planted)
    check(f'... with their signs', all((x['coef'] > 0) == (effect[x['term']] > 0) for x in Ts['terms'] if x['term'] in effect), True)
# the Wald tests: at no penalty they are statsmodels' own
Xk = _sp.csr_matrix(TX.weigh(C_.X[:, cols_], 'binary'))[:, :5]
mle = sm.GLM(yy, sm.add_constant(Xk.toarray()), family=sm.families.Binomial()).fit()
fit0 = {'coef': np.asarray(mle.params[1:]), 'intercept': float(mle.params[0]), 'lambda': 0.0, 'sd': np.ones(5)}
_, pw = TX.enet_wald(Xk, yy, 'binomial', fit0)
check.near('enet_wald with no penalty: statsmodels\' Wald p-values of the logistic fit', mx(pw, mle.pvalues[1:]), 0.0, abs_=1e-8)
ols = sm.OLS(score, sm.add_constant(Xk.toarray())).fit()
_, pn = TX.enet_wald(Xk, score, 'normal', {'coef': np.asarray(ols.params[1:]), 'intercept': float(ols.params[0]), 'lambda': 0.0, 'sd': np.ones(5)})
check.near('... and of the linear fit (their t tests as normal ones, the p-values of large samples)', mx(pn, 2 * __import__('scipy').stats.norm.sf(np.abs(ols.tvalues[1:]))), 0.0, abs_=1e-10)
Ti_ = call('text.termsel', table=ts_t, column='t', response='yes', target='maybe')
check('Term Selection: a target that is not a level, a character ordinal, the text as the response: errors', ('not a level' in Ti_['error'], 'response' in call('text.termsel', table=ts_t, column='t', response='t')['error']), (True, True))
Ts_d = call('text.termsel', table=ts_t, column='t', response='y', min_freq=10)
D_ = Ts_d['docs']
bb = {x['term']: x['coef'] for x in Ts_d['terms']}
contrib = [sum(bb.get(w, 0) for w in set(t.split()) if bb.get(w, 0) > 0) for t in stexts]
check.near('Document Scores: each document\'s positive contribution, the sum of its kept positive terms\' coefficients (Binary)', mx(D_['positive'], contrib), 0.0, abs_=1e-9)
check.near('... and the prediction: the intercept plus both contributions', mx(D_['predicted'], np.array(D_['positive']) + np.array(D_['negative']) + Ts_d['intercept']), 0.0, abs_=1e-9)

# ---- Sentiment Analysis: VADER called directly ------------------------------------------------------------------------------------------------------------------------------
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    have_vader = True
except ImportError:
    have_vader = False
    print('      (vaderSentiment is not installed: the Sentiment Analysis checks skipped)')
if have_vader:
    an = SentimentIntensityAnalyzer()
    se_texts = ['The courier was VERY friendly and fast!', 'Not good at all, the parcel was damaged.', 'It arrived.', 'I love it but the price is terrible.',
                'Customer service was not helpful', '', 'Absolutely wonderful, thank you!!', 'The app keeps crashing, awful.']
    se_t = table({'t': [x or None for x in se_texts], 'g': ['a', 'a', 'b', 'b', 'c', 'c', 'd', 'd']})
    Se = call('text.sentiment', table=se_t, column='t')
    want_ = [an.polarity_scores(x) for x in se_texts]
    check.near('Sentiment: each document\'s compound, positive, neutral and negative scores are VADER\'s own', max(mx(Se['docs']['compound'], [w['compound'] for w in want_]), mx(Se['docs']['pos'], [w['pos'] for w in want_]),
               mx(Se['docs']['neu'], [w['neu'] for w in want_]), mx(Se['docs']['neg'], [w['neg'] for w in want_])), 0.0, abs_=1e-12)
    comp_ = np.array([w['compound'] for w in want_])
    check('... the summary: positive from 0.05, negative from -0.05 (VADER\'s thresholds)', (Se['summary']['positive'], Se['summary']['negative'], Se['summary']['neutral']),
          (int(np.sum(comp_ >= 0.05)), int(np.sum(comp_ <= -0.05)), int(np.sum((comp_ > -0.05) & (comp_ < 0.05)))))
    import string  # noqa: E402
    words_ = [[x.strip(string.punctuation) for x in t.lower().split()] for t in se_texts]
    lexc = collections.Counter(w for ws in words_ for w in ws if w in an.lexicon)
    check('... the Sentiment Terms: the words of its lexicon in the texts, their valences and counts', {x['term']: (x['score'], x['count']) for x in Se['lexicon']}, {w: (an.lexicon[w], c) for w, c in lexc.items()})
    check('... the negations met (not, n\'t) and the intensifiers (very, absolutely)', ({x['term'] for x in Se['negations']}, {x['term'] for x in Se['intensifiers']}), ({'not'}, {'very', 'absolutely'}))
    check('... each document\'s bar of the histogram is np.histogram\'s', Se['docs']['bin'], (np.clip(np.searchsorted(np.linspace(-1, 1, 21), comp_, side='right') - 1, 0, 19)).tolist())
    counts_, _ = np.histogram(comp_, bins=np.linspace(-1, 1, 21))
    check('... and the bars\' counts are np.histogram\'s', np.bincount(Se['docs']['bin'], minlength=20).tolist(), counts_.tolist())
    Sg = call('text.sentiment', table=se_t, column='t', id_col='g')
    joined_ = ['\n'.join(x for x in se_texts[2 * i:2 * i + 2] if x) for i in range(4)]
    check.near('... with an ID: a document is the texts of its rows, one after another', mx(Sg['docs']['compound'], [an.polarity_scores(x)['compound'] for x in joined_]), 0.0, abs_=1e-12)
else:
    Se = None

# ---- the new analyses' Python, run on CSV exports: the report's numbers ---------------------------------------------------------------------------------------
DUMP2 = """
import json as _j
_o = {}
for _k in ("pi", "P", "R", "most_likely", "cluster", "Z", "term_scores", "scores", "chosen", "kept", "p"):
    if _k in globals():
        _v = globals()[_k]
        _o[_k] = _v.to_dict("split") if hasattr(_v, "to_dict") and not isinstance(_v, dict) else (_v.tolist() if hasattr(_v, "tolist") else _v)
print("@@" + _j.dumps(_o, default=float))
"""


def run2(code):
    p_ = subprocess.run([sys.executable, '-c', code + DUMP2], cwd=work, capture_output=True, text=True, timeout=600)
    if p_.returncode:
        print(p_.stderr[-3000:])
        return None
    return json.loads(next(ln for ln in p_.stdout.splitlines() if ln.startswith('@@'))[2:])


for kw in ({}, {'stemming': 'combine', 'id_col': 'customer'}, {'rows': list(range(0, 400, 2))}):
    rr_ = call('text.lca', table=tid2, column='comment', n_clusters=3, min_freq=2, max_terms=60, seed=5, table_name='Comments', **kw)
    o = run2(rr_['code'])
    if check(f'the Latent Class Analysis code runs ({kw})', o is not None, True):
        check.near(f'... and gives its mixing and term probabilities and each document\'s ({kw})', max(mx(o['pi'], rr_['pi']), mx(np.array(o['P']).T, rr_['P']), mx(o['R'], rr_['R'])), 0.0, abs_=1e-12)
        check(f'... and the most likely clusters ({kw})', o['most_likely'], rr_['likely'])
for kind in ('terms', 'docs'):
    for kw in ({}, {'id_col': 'customer', 'n_clusters': 4}):
        cc = call('text.cluster', table=tid2, column='comment', kind=kind, min_freq=2, max_terms=60, k=6, seed=5, table_name='Comments', **kw)
        o = run2(cc['code'])
        if check(f'the Cluster {kind.title()} code runs ({kw})', o is not None, True):
            check(f'... and gives the report\'s clusters ({kw})', o['cluster'], cc['labels'])
        o = run2(cc['dendro_head'].replace('import matplotlib.pyplot as plt\n', ''))
        if check(f'the dendrogram\'s lines run ({kind}, {kw})', o is not None, True):
            check.near(f'... and give the report\'s joins ({kind}, {kw})', mx(np.array(o['Z'])[:, 2], cc['heights']), 0.0, abs_=1e-12)
pd.DataFrame({'t': stexts, 'y': score, 'yes': ['yes' if v else 'no' for v in yb], 'rid': [f'r{i}' for i in range(500)]}).to_csv(os.path.join(work, 'Scores.csv'), index=False)
frame_s = pd.read_csv(os.path.join(work, 'Scores.csv'), dtype=str, keep_default_na=False)
for kw in ({'response': 'y'}, {'response': 'yes', 'target': 'yes'}, {'response': 'yes', 'target': 'no', 'weighting': 'tfidf', 'early': False}):
    tt_ = call('text.termsel', table=ts_t, column='t', min_freq=10, table_name='Scores', **kw)
    o = run2(tt_['code'])
    if check(f'the Term Selection code runs ({kw})', o is not None, True):
        ts_ = o['term_scores']
        cix = {c: k for k, c in enumerate(ts_['columns'])}
        check(f'... and gives its terms ({kw})', [x[cix['Term']] for x in ts_['data']], [x['term'] for x in tt_['terms']])
        check.near(f'... their coefficients and LogWorths ({kw})', mx([[x[cix['Coefficient']], x[cix['LogWorth']]] for x in ts_['data']], [[x['coef'], x['logworth']] for x in tt_['terms']]), 0.0, abs_=1e-9)
    figs, err = run_snippet(tt_['plot_code']['bars'], frame_s, 'Scores', work)
    if check(f'the term coefficients\' bars: the code runs ({kw})', err, None) and figs:
        ax = figs[0]['axes'][0]
        top = sorted(tt_['terms'], key=lambda x: -abs(x['coef']))[:30][::-1]
        check.near(f'... a bar per kept term, its coefficient ({kw})', mx([b['w'] for b in ax['bars']], [x['coef'] for x in top]), 0.0, abs_=1e-12)
        check(f'... named on the axis, the largest at the top ({kw})', ax['yticklabels'], [x['term'] for x in top])
if have_vader:
    pd.DataFrame({'t': se_texts, 'g': ['a', 'a', 'b', 'b', 'c', 'c', 'd', 'd']}).to_csv(os.path.join(work, 'Sentiments.csv'), index=False)
    frame_v = pd.read_csv(os.path.join(work, 'Sentiments.csv'), dtype=str, keep_default_na=False)
    for kw in ({}, {'id_col': 'g'}):
        sv_ = call('text.sentiment', table=se_t, column='t', table_name='Sentiments', **kw)
        o = run2(sv_['code'])
        if check(f'the Sentiment Analysis code runs ({kw})', o is not None, True):
            sc_ = o['scores']
            cix = {c: k for k, c in enumerate(sc_['columns'])}
            check.near(f'... and gives each document\'s scores ({kw})', mx([[x[cix[c]] for c in ('compound', 'pos', 'neu', 'neg')] for x in sc_['data']],
                       [[sv_['docs'][k][d] for k in ('compound', 'pos', 'neu', 'neg')] for d in range(len(sv_['docs']['compound']))]), 0.0, abs_=1e-12)
        figs, err = run_snippet(sv_['plot_code']['hist'], frame_v, 'Sentiments', work)
        if check(f'the sentiment histogram: the code runs ({kw})', err, None) and figs:
            ax = figs[0]['axes'][0]
            check(f'... bars of 0.1 from -1 to 1, each the documents in it ({kw})', [round(b['h']) for b in ax['bars']], np.bincount(sv_['docs']['bin'], minlength=20).tolist())
LM = call('text.lca', table=tid2, column='comment', n_clusters=4, min_freq=2, max_terms=60, seed=5, table_name='Comments')
F = fig_of(LM['plot_code']['mds'], 'the LCA\'s MDS Plot')
if F:
    ax = F['axes'][0]
    check.near('... a point per cluster at its MDS coordinates', mx(ax['scatter'][0]['xy'], LM['coords']), 0.0, abs_=1e-12)
    check('... named by its cluster, at its point', ([t['s'] for t in ax['texts']], mx([[t['x'], t['y']] for t in ax['texts']], LM['coords'])), ([f'Cluster {c + 1}' for c in range(4)], 0.0))

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
