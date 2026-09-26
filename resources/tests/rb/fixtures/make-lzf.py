#!/usr/bin/env python3
"""Write lzf.h5, the fixture test-lazy.py reads: data compressed with h5py's
LZF filter (id 32000), which h5wasm cannot decode without a plugin. The values
are made up, and chosen so that a wrong decode cannot pass for a right one.

    python3 make-lzf.py        # needs h5py
"""
import h5py
import numpy as np

t = np.logspace(0, 4, 50)
with h5py.File('lzf.h5', 'w') as f:
    f.create_dataset('time', data=t).attrs['unit'] = 'years'
    x = f.create_dataset('x', data=np.arange(2000) * 0.5, compression='lzf', chunks=(500,))
    x.attrs['time_dependent'] = 'FALSE'
    g = f.create_group('bio')
    g.attrs['IndexLists'] = ['Radionuclides']
    g.attrs['time_dependent'] = 'TRUE'
    g.attrs['unit'] = 'Bq'
    for name, scale, compression in (('Cs-137', 100, 'lzf'), ('I-129', 1000, 'gzip')):
        d = g.create_dataset(name, data=t / scale, compression=compression, chunks=(25,))
        d.attrs['time_dependent'] = 'TRUE'
        d.attrs['unit'] = 'Bq'
