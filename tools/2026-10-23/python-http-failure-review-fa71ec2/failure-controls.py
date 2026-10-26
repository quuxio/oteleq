"""Timeout errors retain identity/notes; wrong worker bodies still fail after join."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

root = Path(sys.argv[1]);base = Path(__file__).resolve().parent
sys.path[:0] = [str(root), str(root / 'tests')]
rows = []
for label, path in [('before', base / 'before-test_python_http_context.py'),
                    ('after', root / 'tests/test_python_http_context.py')]:
    spec = importlib.util.spec_from_file_location('http_timeout_' + label, path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    error = subprocess.TimeoutExpired('controlled fixture', 1,
                output=b'OMITTED_STDOUT_PREFIX' + b'x' * 70000 + b'STDOUT_TAIL',
                stderr=b'OMITTED_STDERR_PREFIX' + b'y' * 70000 + b'STDERR_TAIL')
    case = module.PythonHttpContextTests()
    caught = None
    with mock.patch.object(module.subprocess, 'run', side_effect=error), \
            mock.patch.object(module.subprocess, 'Popen', side_effect=AssertionError('must not launch')) as spawn:
        try:case.test_native_wsgi_close_keeps_getter_side_effects_and_the_second_lookup_callable()
        except BaseException as failure:caught=failure
    spawn.assert_not_called()
    assert caught is not None
    assert (caught is error) == (label == 'after')
    text = '\n'.join(getattr(caught, '__notes__', ())) if label == 'after' else str(caught)
    assert 'STDOUT_TAIL' in text and 'STDERR_TAIL' in text
    assert 'OMITTED_STDOUT_PREFIX' not in text and 'OMITTED_STDERR_PREFIX' not in text
    assert len(text) < 140000
    rows.append({'case':label,'exception':type(caught).__name__,'original_identity_preserved':caught is error,
                 'bounded_notes_bytes':len(text),'tails_present':True,'prefixes_omitted':True,'applications_started':0})
import test_python_http_components as component
original = component.urllib.request.urlopen
def altered(*args, **kwargs):
    response = original(*args, **kwargs)
    read = response.read
    def different(*values, **options):
        read(*values, **options)
        return b'9'
    response.read = different
    return response
result = unittest.TestResult()
with mock.patch.object(component.urllib.request, 'urlopen', side_effect=altered):
    component.PythonHttpComponentTests('test_parallel_transport_injection_keeps_requests_unmodified_in_flight').run(result)
assert len(result.failures) == 1 and not result.errors
assert "b'9'" in result.failures[0][1]
rows.append({'case':'wrong_worker_body','failures':len(result.failures),'errors':len(result.errors),'body_oracle_detected':True})
print(json.dumps(rows))
