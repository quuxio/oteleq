"""Compiler/loader roots must not invent executions for uncalled code."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-8e8b4fb'
sys.path[:0] = [str(SOURCE / 'tests'), str(SOURCE)]
from test_python_loader_origins import PythonLoaderOriginTests

runtime = '312' if sys.version_info[:2] == (3, 12) else '314'
folder = ROOT / ('unexecuted-roots-' + runtime)
folder.mkdir()
PythonLoaderOriginTests.setUpClass()
case = PythonLoaderOriginTests()
case.setUp()
rows = []
try:
    for label, body, expected in (
        ('compiled-only', "code=loader.get_code('target')\nprint('compiled only')\n", 0),
        ('module-only', "code=loader.get_code('target');namespace={};exec(code,namespace)\nprint('module only')\n", 1),
    ):
        out, journal = case.application("loader=external.SourceFileLoader('target',path)\n" + body)
        assert journal.capture_complete
        roots = [root for root in journal.roots if root.route == 2]
        assert len(roots) == 1
        executions = [value for value in journal.executions if value.root == roots[0].identity]
        assert len(executions) == expected
        assert out == (label.replace('-', ' ') + '\n').encode()
        original = case.root / ('input-' + str(case.number) + '.journal')
        shutil.copyfile(original, folder / (label + '.journal'))
        rows.append({'case': label, 'loader_roots': 1, 'actual_code_executions': len(executions),
                     'expected_code_executions': expected, 'capture_complete': True,
                     'raw_journal_sha256': hashlib.sha256(original.read_bytes()).hexdigest()})
finally:
    case.doCleanups()
manifest = json.loads((ROOT / 'source-8e8b4fb.json').read_text())
changed = [name for name, digest in manifest['files'].items()
           if hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != digest]
assert not changed, changed
result = {'head': manifest['head'], 'python': sys.version, 'source_files_preserved': len(manifest['files']),
          'controls': rows, 'scope': 'native loader component; public source admission remains unavailable'}
(folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
