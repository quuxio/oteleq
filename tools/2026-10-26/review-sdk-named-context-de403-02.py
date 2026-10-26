"""Review the shared context/named engine composition without native builds."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
SDK = Path('/Users/sclarke/github/otelc-qualification')
OUT = BASE / '2026-10-26/sdk-named-context-de403-review-02'
HEAD = 'de4031d2aa19088e8cd31845c8f4a8900de863a5'
RUST = 'cf8fdb766b5683bd079548f72bdedade985987b6'
CONTEXT = '8be4307d0eb025717908faf2b321af1561e09bbf'
SONAR = '794d2d55a4ba81683a5b99078301cffe27f87556'
MODULES = ('test_rust_prepared', 'test_rust_owned_build', 'test_rust_lifetimes',
           'test_rust_telemetry', 'test_rust_capture_records',
           'test_rust_histogram_observation', 'test_native_sonar')


def bounded(version: str, root: Path) -> dict:
    """Replay original component controls and keep each interpreter's coverage."""
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    data = OUT / (version + '.coverage')
    argv = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--source=otelc.prepared_rust,otelc.rust_supervisor,ci.rust_telemetry,ci.histogram_observation,ci.native_sonar',
            '-m', 'unittest', *MODULES, '-v']
    environment = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(root / 'tests')}
    result = subprocess.run(argv, cwd=root, env=environment, capture_output=True, text=True, timeout=120)
    (OUT / (version + '.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0 and re.search(r'Ran 83 tests', result.stderr) and '\nOK\n' in result.stderr
    report = OUT / (version + '-coverage.json')
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}', '-o', str(report)],
                   cwd=root, env=environment, capture_output=True, check=True, timeout=30)
    floors = {name: value['summary'] for name, value in json.loads(report.read_text())['files'].items()}
    assert len(floors) == 5 and all(item['percent_covered'] >= 80 for item in floors.values()), floors
    return {'python': version, 'methods': 83, 'module_coverage': floors, 'argv': argv}


def main() -> None:
    """Prove exact runtime composition and preserve every frozen source fact."""
    OUT.mkdir(exist_ok=False)
    manifest = json.loads((SDK / '2026-10-26/native-named-owned-context/source/source.json').read_text())
    root = Path(manifest['root'])
    spec = importlib.util.spec_from_file_location('guard', BASE / '2026-10-26/review-python-label-bound.py')
    guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    held = guard.check_source(manifest)
    git = lambda *args: subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    blob = lambda revision, path: subprocess.check_output(['git', 'show', revision + ':' + path], cwd=root).decode()
    assert manifest['head'] == git('rev-parse', 'HEAD') == HEAD and not git('status', '--porcelain')
    assert git('show', '-s', '--format=%P', HEAD).split() == ['c9b55f531b49d9d6e709fc3a84165445f93dc251', SONAR]
    assert git('show', '-s', '--format=%P', 'c9b55f531b49d9d6e709fc3a84165445f93dc251').split() == [RUST, CONTEXT]
    cpp = 'adapters/native/src/function_runtime.cpp'
    old = blob(CONTEXT, cpp); donor = blob(RUST, cpp); current = (root / cpp).read_text()
    start = 'std::uint64_t FunctionRuntime::EnterNamed(std::string_view name) noexcept {'
    end = 'std::uint64_t FunctionRuntime::Enter(const void *address) noexcept {'
    named = donor[donor.index(start):donor.index(end)]
    assert named.startswith(start) and current[current.index(start):current.index(end)] == named
    old = old.replace('#include <map>\n', '#include <map>\n#include <set>\n', 1)
    old = old.replace('  std::map<const void *, std::string> functions;\n',
                      '  std::map<const void *, std::string> functions;\n  std::set<std::string, std::less<>> named_functions;\n', 1)
    old = old.replace(end, named + end, 1)
    assert old == current, 'runtime differs beyond reviewed context engine plus exact named-entry code'
    header = 'adapters/native/include/otelc/function_runtime.h'
    old = blob(CONTEXT, header); donor = blob(RUST, header)
    first = '  std::uint64_t Enter(const void *address) noexcept;\n'
    last = '  bool Leave(std::uint64_t token, std::int32_t unwinding) noexcept;'
    named_header = donor[donor.index(first) + len(first):donor.index(last)]
    assert old.replace('#include <memory>\n', '#include <memory>\n#include <string_view>\n', 1).replace(
        first, first + named_header, 1) == (root / header).read_text()
    identical = ('native/llvm/function_abi.h',
                 'adapters/native/include/otelc/object_runtime.h',
                 'adapters/native/src/object_runtime.cpp', 'adapters/native/launcher/src/runtime.cpp')
    for path in identical: assert blob(RUST, path) == (root / path).read_text(), path
    assert blob(SONAR, 'ci/native_sonar.py') == (root / 'ci/native_sonar.py').read_text()
    workflow = (root / '.github/workflows/native-context.yml').read_text()
    assert 'git archive --format=tar --output build/native-context/before-source.tar 98b3cfedd685170cfa71e71b2a7e6f10ad40c416' in workflow
    assert 'git show e0e0991d66723608ec2775cebb4cf2b28eb133a4:adapters/native/tests/function_runtime_test.cpp' in workflow
    assert 'mixed address/named SDK groups passed' in workflow
    with ThreadPoolExecutor(max_workers=2) as pool:
        tests = list(pool.map(lambda version: bounded(version, root), ('312', '314')))
    assert guard.check_source(manifest) == held
    result = {'status': 'clear for exact shared-engine source composition and bounded Python controls',
              'head': HEAD, 'source_preservation': held, 'tests': tests,
              'composition': 'Function runtime exactly reviewed8be context implementation plus exactcf8 named registry/EnterNamed/include; header has exact named declaration/include only.',
              'preserved_runtime_files': list(identical),
              'native_analysis_importer': 'Complete ci/native_sonar.py byte-identical to reviewed794 correction.',
              'manual_review': [
                  'Named lookup copies a stable set-node key, shares the existing function budget, releases registry lock/ProbeGuard before ordinary Enter, and preserves SavedErrno and allocation-failure accounting.',
                  'Existing context lease ownership, nested parent order, final-reference release outside bookkeeping lock, thread/capacity refusal and close accounting are unchanged.',
                  'Mixed address/named parent/child cases cover ended parents, reused worker, nested calls and ambient SDK context under all four metric states; object/resource/drop errno cases remain separately compiled runtime requirements.',
                  'Historical deadlock control pins original98b runtime and e0 regression test rather than compiling new named API tests against an unavailable old API. Current mixed-case success marker is independently required.',
                  'Docs keep automatic task hooks, public context/health/transport and general propagation unavailable. No format/C probe ABI or new source-edit requirement is introduced.'
              ], 'native_builds': 0, 'sdk_builds': 0, 'application_launches': 0,
              'limits': 'Source/composition/bounded controls only. Genuine current-head Linux/macOS C++/SDK/Rust compilation/runtime/coverage and all protected checks remain required. No earlier runtime qualification transfers to the new engine.'}
    (OUT / 'review.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'head': HEAD, 'files': held['files'],
                      'methods_each_python': 83,
                      'review_sha256': hashlib.sha256((OUT / 'review.json').read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
