"""A setup error cannot stand in for a deliberate final input-mutation failure."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

root = Path(sys.argv[1])
base = Path(__file__).resolve().parent
sys.path[:0] = [str(root), str(root / 'tests')]
rows = []
for name, path in [('before', base / 'before-test_python_stock_benchmark.py'),
                   ('after', root / 'tests/test_python_stock_benchmark.py')]:
    spec = importlib.util.spec_from_file_location('stock_phase_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = module.PythonStockBenchmarkTests
    method = 'test_changed_source_or_policy_cannot_be_a_closed_stock_receipt'
    original_popen = subprocess.Popen
    owners = []
    def spawn(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        owners.append(process)
        return process
    with mock.patch.object(cls, 'inspect', side_effect=ValueError('controlled changed setup')), \
            mock.patch.object(subprocess, 'Popen', side_effect=spawn):
        result = unittest.TestResult()
        cls(method).run(result)
    assert result.wasSuccessful() == (name == 'before')
    applications = [p for p in owners if any(str(a).endswith('/BenchmarkApp.py') for a in p.args)]
    assert len(applications) == 2 and all(p.poll() is not None for p in applications)
    setup = {'accepted': result.wasSuccessful(), 'failures': len(result.failures),
             'errors': len(result.errors), 'applications_reaped': len(applications)}
    with mock.patch.object(module.stock, 'verify'):
        result = unittest.TestResult()
        cls(method).run(result)
    assert len(result.failures) == 2 and not result.errors
    rows.append({'version': name, 'setup_error': setup, 'verification_bypass_failures': 2})
print(json.dumps(rows))
