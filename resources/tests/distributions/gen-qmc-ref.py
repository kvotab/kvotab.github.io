#!/usr/bin/env python3
"""Writes qmc-ref.json: SciPy's plain (unscrambled) Sobol and Halton points,
the first 64 in each of the 16 dimensions distributions.html's sequences
have, for test-engine.mjs to compare sampling.js with.

    python3 resources/tests/distributions/gen-qmc-ref.py

SciPy's Sobol uses Joe and Kuo's direction numbers (new-joe-kuo-6.21201),
as sampling.js does; its points are k / 2^30 and sampling.js's k / 2^32, the
same numbers.
"""
import json
import os

import scipy
from scipy.stats import qmc

HERE = os.path.dirname(os.path.abspath(__file__))
out = {
    'scipy': scipy.__version__,
    'sobol': qmc.Sobol(d=16, scramble=False).random(64).T.tolist(),
    'halton': qmc.Halton(d=16, scramble=False).random(64).T.tolist(),
}
with open(os.path.join(HERE, 'qmc-ref.json'), 'w') as f:
    json.dump(out, f, separators=(',', ':'))
print('wrote qmc-ref.json with SciPy', scipy.__version__)
