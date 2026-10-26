"""Demonstrate a false-green fixture failure, then refuse a bypassed decoder."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

root = Path(sys.argv[1])
base = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
rows = []
for name, path in [('before', base / 'before-test_python_code_index.py'),
                   ('after', root / 'tests/test_python_code_index.py')]:
    spec = importlib.util.spec_from_file_location('index_test_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    method = 'test_header_types_sizes_versions_and_entry_offsets_are_closed'
    with mock.patch.object(module, 'record', side_effect=ValueError('controlled broken fixture')):
        result = unittest.TestResult()
        module.PythonCodeIndexTests(method).run(result)
    assert result.wasSuccessful() == (name == 'before')
    fixture = {'accepted': result.wasSuccessful(), 'failures': len(result.failures),
               'errors': len(result.errors)}
    with mock.patch.object(module.index, 'decode', return_value=object()):
        result = unittest.TestResult()
        module.PythonCodeIndexTests(method).run(result)
    assert result.failures and not result.errors
    rows.append({'version': name, 'fixture_fault': fixture,
                 'decoder_bypass_failures': len(result.failures)})
assert rows[0]['decoder_bypass_failures'] == rows[1]['decoder_bypass_failures']
print(json.dumps(rows))
