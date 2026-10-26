"""Review owner-bound Sonar contexts with the original failing regression."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-26/native-analysis-component-context/source/source.json')
OUT = BASE / '2026-10-26/sdk-native-analysis-794d-review'


def run(version: str, source: Path) -> dict:
    """Require the exact old duplicate failure, then pass all current tests."""
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': f'{source}:{source}/tests'}
    control = '''import importlib.util, pathlib, sys, unittest
import ci
spec = importlib.util.spec_from_file_location('old_native_sonar', sys.argv[1])
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
ci.native_sonar = old
namespace = {'__name__': 'maintained_regression', '__file__': sys.argv[2]}
exec(compile(pathlib.Path(sys.argv[2]).read_bytes(), sys.argv[2], 'exec'), namespace)
suite = unittest.TestSuite([namespace['NativeSonarTests']('test_analysis_uses_each_coverage_producers_own_compilation_context')])
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
'''
    old = subprocess.run([str(python), '-B', '-c', control, str(OUT / 'original-native-sonar.py'),
                          str(source / 'tests/test_native_sonar.py')], cwd=source, env=env,
                         capture_output=True, text=True, timeout=60)
    (OUT / (version + '-original-regression.log')).write_text(old.stdout + old.stderr)
    assert old.returncode == 1 and 'native compilation unit is duplicated' in old.stderr
    assert 'Ran 1 test' in old.stderr and 'FAILED (errors=1)' in old.stderr
    data = OUT / (version + '.coverage')
    args = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--source=ci.native_sonar', '-m', 'unittest', 'test_native_sonar', '-v']
    current = subprocess.run(args, cwd=source, env=env, capture_output=True, text=True, timeout=60)
    (OUT / (version + '-current-tests.log')).write_text(current.stdout + current.stderr)
    assert current.returncode == 0 and 'Ran 12 tests' in current.stderr and '\nOK\n' in current.stderr
    report = OUT / (version + '-coverage.json')
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}', '-o', str(report)],
                   cwd=source, env=env, check=True, capture_output=True, timeout=30)
    coverage = json.loads(report.read_text())['totals']
    assert coverage['percent_covered'] >= 80
    return {'python': version, 'original_regression_exit': old.returncode,
            'current_exit': current.returncode, 'current_methods': 12, 'coverage': coverage}


def main() -> None:
    """Preserve exact sources, the old helper blob, tests and scoped result."""
    OUT.mkdir(exist_ok=False)
    spec = importlib.util.spec_from_file_location('source_guard', BASE / '2026-10-26/review-python-label-bound.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['head'] == '794d2d55a4ba81683a5b99078301cffe27f87556'
    source = Path(manifest['root'])
    before = guard.check_source(manifest)
    changed = subprocess.check_output(['git', 'diff', '--name-only', manifest['base'], manifest['head']],
                                      cwd=source, text=True).splitlines()
    assert set(changed) == {'ci/native_sonar.py', 'tests/test_native_sonar.py', 'docs/llvm-backend.md'}
    original = subprocess.check_output(['git', 'show', manifest['base'] + ':ci/native_sonar.py'], cwd=source)
    (OUT / 'original-native-sonar.py').write_bytes(original)
    subprocess.run(['git', 'diff', '--check', manifest['base'], manifest['head']], cwd=source, check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(lambda version: run(version, source), ('312', '314')))
    subprocess.run(['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',
                    str(BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),
                    'docs/llvm-backend.md'], cwd=source, check=True, capture_output=True)
    after = guard.check_source(manifest)
    assert before == after
    record = {'status': 'clear for exact three-file producer-owned analysis-context correction',
              'head': manifest['head'], 'base': manifest['base'], 'source_preservation': after,
              'changed': changed, 'checks': checks, 'findings': [],
              'original_helper_sha256': hashlib.sha256(original).hexdigest(),
              'manual_review': [
                  'Each production source uses the same checked component record for coverage and compilation context; native test units remain assigned to their SDK control producer.',
                  'Complete original databases and their identities stay intact. A sibling shared unit cannot replace a missing owner entry; duplicate entries within an owner still refuse.',
                  'Existing source/header/LCOV identities and per-source logical plus physical coverage floors are unchanged. Literal commands are retained, never executed.',
                  'The new maintained shared-source regression fails on the original helper with the exact duplicate error on both interpreters; all12 current tests pass, including missing-owner and duplicate-owner refusals.',
              ], 'local_compiler_builds': 0, 'local_sdk_builds': 0, 'local_application_launches': 0,
              'limits': 'Metadata importer/source review only. Original hosted failure is preserved; full current-head Linux/macOS/Sonar analysis and broader SDK/provider delivery remain separate.'}
    (OUT / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
