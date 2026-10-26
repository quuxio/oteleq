"""Retain old-head refusal failures and focused corrected-source checks."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path(__file__).resolve().parent
SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
OLD = BASE.parent / 'go-bounded-cache/source-ae849aa'
PYTHON = BASE.parent.parent / '2026-10-24/python-live-metrics/env-312/bin/python'
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=os.pathsep.join(str(SOURCE / name) for name in ['tests', 'adapters/generation', 'examples']))
tools = json.loads((BASE.parent / 'go-bounded-cache/full-gate-ae849aa/command.json').read_text())['selected_tools']
environment.update(tools)
negative = '''import runpy, sys, unittest
from pathlib import Path
old = Path(sys.argv[1])
sys.path[:0] = [str(old / 'examples'), str(old / 'adapters/generation')]
import generation, go_cache, java_project, otelc_capture
scope = runpy.run_path(sys.argv[2], run_name='old_case_alias_controls')
case = scope['PathBoundaryTests']
names = ['test_output_and_sdk_cache_paths_refuse_source_aliases_before_writes',
         'test_temporary_source_alias_refuses_before_tempfile_writability_probe']
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(case(name) for name in names))
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
commands = {
    'corrected-focused-selected-tools': [str(PYTHON), '-B', '-m', 'unittest', '-v',
                          'test_capture_paths', 'test_generation_go_cache',
                          'test_generation_java_project', 'test_generation',
                          'test_capture_go', 'test_capture_languages'],
}
records = json.loads((BASE / 'regressions.json').read_text())['records']
for name, command in commands.items():
    started = time.monotonic()
    with (BASE / (name + '.stdout')).open('xb') as stdout, (BASE / (name + '.stderr')).open('xb') as stderr:
        result = subprocess.run(command, cwd=SOURCE, env=environment,
                                stdout=stdout, stderr=stderr, timeout=600)
    records[name] = {'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 3),
                     'expected': 'failure on actual macOS case aliases' if name.startswith('old') else 'pass'}
    (BASE / 'regressions.json').write_text(json.dumps({'finished': datetime.now(timezone.utc).isoformat(),
                                                     'records': records}, indent=2) + '\n')
    print(name, json.dumps(records[name]), flush=True)
    if (name.startswith('old') and result.returncode == 0) or (not name.startswith('old') and result.returncode != 0):
        raise SystemExit(1)
