"""Retain full assertion output for the actual terminal owner-cleanup failure."""

import json
import os
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parent
source = BASE / 'source-314'
sys.path[:0] = [str(source), str(source / 'tests')]
os.environ['PYTHONPATH'] = str(source) + os.pathsep + str(source / 'tests')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
from test_python_prepared import PreparedPythonTests

PreparedPythonTests.maxDiff = None
suite = unittest.TestSuite(PreparedPythonTests('test_public_owner_cleans_children_when_the_supervisor_is_killed')
                           for _ in range(12))
with (BASE / 'owner-cleanup-focused.log').open('w') as stream:
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
record = {'head': '406260df97d35dfb35daa4274a6e9651eada4394', 'python': sys.version,
          'runs': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
          'success': result.wasSuccessful(), 'original_broad_failure_retained': 'tests-314.log'}
(BASE / 'owner-cleanup-focused.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
raise SystemExit(not result.wasSuccessful())
