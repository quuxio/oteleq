"""Retain exact native gate and analysis test counts without skipped evidence."""

import json
from pathlib import Path
import sys
import unittest

source = Path.cwd()
sys.path[:0] = [str(source / 'tests'), str(source)]
suite = unittest.defaultTestLoader.loadTestsFromNames(['test_native_gate', 'test_native_sonar'])
selected = suite.countTestCases()
result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = {'selected': selected, 'tests_run': result.testsRun, 'skipped': len(result.skipped),
           'failures': len(result.failures), 'errors': len(result.errors), 'successful': result.wasSuccessful()}
Path(sys.argv[1]).write_text(json.dumps(summary, indent=2) + '\n')
raise SystemExit(0 if result.wasSuccessful() and not result.skipped and result.testsRun == selected else 1)
