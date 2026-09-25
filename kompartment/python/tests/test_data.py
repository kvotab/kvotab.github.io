"""The data files written from the application's sources are current."""

from __future__ import annotations

import subprocess
import unittest

from helpers import NODE, PACKAGE, needs_app


@needs_app
class GeneratedData(unittest.TestCase):
    def test_the_nuclide_table_and_reserved_names_are_current(self):
        proc = subprocess.run([NODE, str(PACKAGE / 'tools' / 'gen_data.mjs'), '--check'],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == '__main__':
    unittest.main()
