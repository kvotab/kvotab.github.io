#!/usr/bin/env python3
"""The .jmp files test_jmp.py reads: the test tables of JMPReader.jl
(https://github.com/jaakkor2/JMPReader.jl, MIT licence), which the page's
reader (resources/py/smui/jmp.py) is a port of, at the commit ported. They
are not ours, so they are fetched into resources/tests/smui/local/jmp/
(git-ignored), not kept in the repository.

    python3 resources/tests/smui/fetch-jmp-fixtures.py
"""
import os
import shutil
import ssl
import subprocess
import urllib.request

try:                                  # a Python without the system's certificates (python.org's, as installed)
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = None

COMMIT = 'a0bc789e7f384b05dccc6797085bf14e15d9e0dd'
FILES = ['example1.jmp', 'compressed.jmp', 'date.jmp', 'duration.jmp', 'time.jmp', 'longcolumnnames.jmp', 'singlecolumnsinglerow.jmp',
         'byteintegers.jmp', 'byteintegers_withmissing.jmp', 'byteintegers_notcompressed.jmp', 'geographic.jmp', 'currencies.jmp',
         'rowstate.jmp', 'compact.jmp', 'compact_UInt8.jmp', 'compact_UInt16.jmp', 'compact_UInt32.jmp', 'minusfour.jmp', 'bugMWE4.jmp']
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'local', 'jmp')

os.makedirs(OUT, exist_ok=True)
for f in FILES:
    url = f'https://raw.githubusercontent.com/jaakkor2/JMPReader.jl/{COMMIT}/test/{f}'
    dest = os.path.join(OUT, f)
    try:
        with urllib.request.urlopen(url, context=CTX) as r, open(dest, 'wb') as w:
            w.write(r.read())
    except (urllib.error.URLError, ssl.SSLError):
        # without certificates Python can use (and no certifi): curl, with the system's
        if not shutil.which('curl'):
            raise
        subprocess.run(['curl', '-fsSL', '-o', dest, url], check=True)
    print('fetched', f)
