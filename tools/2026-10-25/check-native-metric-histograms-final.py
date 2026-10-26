"""Freeze and check the complete native metric qualifier without SDK builds."""

import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-metric-histograms')
BASE = Path('/Users/sclarke/github/oteleq-qualification')
OUTPUT = BASE / '2026-10-25/native-metric-controls/histogram-final-components-02'


def main() -> None:
    OUTPUT.mkdir()
    facts = runpy.run_path(str(BASE / '2026-10-25/check-native-metric-oracles.py'))['facts']
    facts.__globals__['ROOT'] = ROOT
    held = facts(); (OUTPUT / 'original-source-facts.json').write_text(json.dumps(held, indent=2) + '\n')
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT / 'tests'),
        OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang', OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++',
        NODE_PATH='/Users/sclarke/github/oteleq-qualification/work/oteleq-native-generated/ci/markdownlint/node_modules')
    checks = []
    def run(argv, label):
        started = time.monotonic()
        result = subprocess.run(list(map(str, argv)), cwd=ROOT, env=environment, capture_output=True, timeout=180)
        for channel in ('stdout', 'stderr'):
            (OUTPUT / (label + '.' + channel)).write_bytes(getattr(result, channel))
        row = {'argv': list(map(str, argv)), 'label': label, 'exit_code': result.returncode, 'seconds': time.monotonic() - started}
        checks.append(row); (OUTPUT / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        if result.returncode:
            print(result.stderr.decode()[-6000:]); print(result.stdout.decode()[-2000:])
        result.check_returncode()
    for version in ('312', '314'):
        python = BASE / ('2026-10-24/python-live-metrics/env-' + version + '/bin/python')
        run(['make', 'native-metric-qualification-check', 'PYTHON=' + str(python)], version)
        run(['make', 'native-metric-control-check', 'PYTHON=' + str(python)], version + '-compatibility')
    python = BASE / '2026-10-24/python-live-metrics/env-312/bin/python'
    run([python, '-m', 'unittest', 'test_generation_native_lifetime_policy', 'test_generation_native_lifetime_frontend',
         'test_generation_native_lifetime_run', 'test_generation_makefile', 'test_generation_policy',
         'test_generation_sequences.SequenceTests.test_malformed_schedules_and_unavailable_requested_adapters_refuse',
         'test_generation_sequences.SequenceTests.test_go_calls_require_source_provider_and_complete_live_states', '-v'], 'shared-compatibility')
    node = '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
    run(['make', 'examples', 'PYTHON=' + str(python), 'NODE=' + node], 'examples')
    run([node, BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js',
         '**/*.md', '--ignore', 'ci/markdownlint/node_modules/**'], 'markdown')
    run(['/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustfmt', '--edition', '2021',
         '--check', 'src/generation.rs'], 'rustfmt')
    run(['git', 'diff', '--check'], 'diff')
    sys.path.insert(0, str(ROOT / 'tests'))
    import native_metric_cases as cases
    syntax = OUTPUT / 'syntax'; syntax.mkdir()
    syntax_inputs = {}
    for language, modes in cases.MODES.items():
        compiler = environment['OTELC_CLANGXX' if language == 'cpp' else 'OTELC_CLANG']
        for mode in modes:
            for changed in (False, True):
                label = language + '-' + mode + ('-changed' if changed else '-original')
                path = syntax / (label + ('.cpp' if language == 'cpp' else '.c'))
                path.write_text(cases.source(language, mode, changed=changed))
                syntax_inputs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                run([compiler, '-std=c++17' if language == 'cpp' else '-std=c11', '-O2',
                     '-Wall', '-Wextra', '-Werror', '-pedantic', '-fsyntax-only', path], label)
                if mode == 'recursive':
                    fixture = syntax / (label + '-fixture'); fixture.mkdir()
                    application, _ = cases.fixture(fixture, language, mode, '11', OUTPUT)
                    helper = application / ('keep.cpp' if language == 'cpp' else 'keep.c')
                    syntax_inputs[str(helper)] = hashlib.sha256(helper.read_bytes()).hexdigest()
                    run([compiler, '-std=c++17' if language == 'cpp' else '-std=c11', '-O2',
                         '-Wall', '-Wextra', '-Werror', '-pedantic', '-fsyntax-only', helper], label + '-helper')
    assert facts() == held
    assert {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in syntax_inputs} == syntax_inputs
    result = {'status': 'passed', 'source_files_held': len(held), 'checks': checks,
        'qualifier_methods_per_python': 29, 'native_control_methods_per_python': 57, 'shared_compatibility_methods': 48,
        'syntax_checks': len(syntax_inputs), 'sdk_builds': 0, 'compiler_builds': 0, 'native_application_launches': 0,
        'scope': 'authored reader/workflow regressions and strict syntax only; genuine SDK matrix remains required'}
    (OUTPUT / 'status.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'checks'}))


if __name__ == '__main__':
    main()
