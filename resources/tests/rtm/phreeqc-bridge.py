#!/usr/bin/env python3
"""PHREEQC for test-phreeqc.js when the WebAssembly build is not there.

stdin {"db": database text, "input": PHREEQC input}; stdout {"rows": the rows of
selected output 99, header first} or {"error": PHREEQC's message}. Needs
phreeqpython (IPhreeqc); the test finds this through RTM_PHREEQC_PYTHON.
"""
import json
import sys

from phreeqpython.viphreeqc import VIPhreeqc

req = json.loads(sys.stdin.read())
ip = VIPhreeqc()
ip.load_database_string(req['db'])
if ip.phc_database_error_count:
    print(json.dumps({'error': ip.get_error_string()}))
    sys.exit(0)
try:
    ip.run_string(req['input'])
except Exception as e:  # VIPhreeqc raises on PHREEQC's input errors
    print(json.dumps({'error': str(e)}))
    sys.exit(0)
ip.dll.SetCurrentSelectedOutputUserNumber(ip.id_, 99)
print(json.dumps({'rows': ip.get_selected_output_array() or []}))
