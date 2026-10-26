"""Check the frozen native/main union without SDK or native compiler builds."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
DAY = BASE / '2026-10-26'
SOURCE = BASE / 'work/oteleq-native-final'
OUT = DAY / 'native-final-components-01'
TARGETS = ('rust-provider-check', 'native-lifetime-workflow-check', 'native-metric-qualification-check', 'capture-forward-check')


def recipes():
    """Use each maintained target's complete module list and coverage denominator."""
    lines = (SOURCE / 'Makefile').read_text().splitlines()
    modules, included = [], []
    for target in TARGETS:
        index = lines.index(target + ':')
        parts = shlex.split(lines[index + 1])
        start = parts.index('unittest') + 1
        modules.extend(parts[start:parts.index('-v', start)])
        included.extend(next(p.split('=', 1)[1] for p in parts if p.startswith('--include=')).split(','))
    return list(dict.fromkeys(modules)), list(dict.fromkeys(included))


def check(version):
    """Keep actual complete test output and every maintained module floor."""
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    modules, included = recipes()
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(SOURCE / 'tests')}
    count_code = 'import sys, unittest; print(unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:]).countTestCases())'
    expected = int(subprocess.check_output([str(python), '-B', '-c', count_code, *modules], cwd=SOURCE, env=env, text=True))
    data = OUT / f'{version}.coverage'
    argv = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}', '--include=' + ','.join(included), '-m', 'unittest', *modules, '-v']
    result = subprocess.run(argv, cwd=SOURCE, env=env, capture_output=True, text=True, timeout=120)
    (OUT / f'{version}.log').write_text(result.stdout + result.stderr)
    count = re.search(r'Ran (\d+) tests', result.stderr)
    assert result.returncode == 0 and count and int(count[1]) == expected, result.stderr[-5000:]
    report = OUT / f'{version}-coverage.json'
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}', '-o', str(report)], cwd=SOURCE, env=env, check=True, capture_output=True)
    measured = {name: item['summary']['percent_covered'] for name, item in json.loads(report.read_text())['files'].items()}
    assert len(measured) == len(included) and min(measured.values()) >= 80, measured
    return {'python': version, 'methods': expected, 'module_floors': measured, 'argv': argv}


if __name__ == '__main__':
    OUT.mkdir()
    spec = importlib.util.spec_from_file_location('guard', DAY / 'review-python-label-bound.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    manifest = json.loads((DAY / 'native-final-source-01/source.json').read_text())
    held = guard.check_source(manifest)
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(check, ('312', '314')))
    for target in TARGETS:
        argv = ['make', target, 'PYTHON=' + str(BASE / '2026-10-24/python-live-metrics/env-312/bin/python')]
        result = subprocess.run(argv, cwd=SOURCE, env=os.environ | {'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, timeout=120)
        (OUT / (target + '.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-3000:]
    assert guard.check_source(manifest) == held
    record = {'status': 'pass for native/main source union and bounded components', 'head': manifest['head'], 'parents': manifest['parents'], 'source_preservation': held, 'checks': checks, 'actual_make_targets': list(TARGETS), 'scope': 'Literal records, private file controls and controlled Python OS helpers; no compiler/SDK/native application builds. Original native runtime evidence remains tied to its original source and CLI bytes.'}
    (OUT / 'checks.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'head': manifest['head'], 'methods_each_python': checks[0]['methods'], 'coverage_modules': len(checks[0]['module_floors']), 'record_sha256': hashlib.sha256((OUT / 'checks.json').read_bytes()).hexdigest()}))
