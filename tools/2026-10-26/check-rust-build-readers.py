"""Validate independent Rust inventory/MIR readers without compiler builds."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
SOURCE = BASE / 'work/oteleq-rust-build-readers'
OUT = BASE / '2026-10-26/rust-build-reader-components-01'
MODULES = ('test_generation_rust_tools', 'test_generation_rust_protocol',
           'test_generation_rust_inventory', 'test_generation_rust_lifetimes',
           'test_generation_native_prepared_inputs',
           'test_generation_native_prepared_build.NativeToolchainAndSDKTests')


def check(version: str) -> dict:
    """Keep each real interpreter's original output and coverage denominator."""
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(SOURCE / 'tests')}
    data = OUT / (version + '.coverage')
    args = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--include=*/rust_tools.py,*/rust_protocol.py,*/rust_inventory.py,*/rust_lifetimes.py',
            '-m', 'unittest', *MODULES, '-v']
    result = subprocess.run(args, cwd=SOURCE, env=env, capture_output=True, text=True, timeout=120)
    (OUT / (version + '-tests.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr[-5000:]
    count = re.search(r'Ran (\d+) tests', result.stderr)
    assert count is not None and int(count[1]) == 44 and '\nOK\n' in result.stderr
    report = OUT / (version + '-coverage.json')
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}', '-o', str(report)],
                   cwd=SOURCE, env=env, check=True, capture_output=True, timeout=30)
    files = json.loads(report.read_text())['files']
    floors = {name: value['summary'] for name, value in files.items()}
    assert len(floors) == 4 and all(value['percent_covered'] >= 80 for value in floors.values())
    return {'python': version, 'argv': args, 'test_methods': int(count[1]), 'module_coverage': floors}


def main() -> None:
    """Run bounded metadata, formatting and actual focused Make checks."""
    OUT.mkdir(exist_ok=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tests = list(pool.map(check, ('312', '314')))
    commands = [
        ['/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustfmt', '--edition', '2021', '--check', 'src/generation.rs'],
        ['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node', str(BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),
         'README.md', 'docs/completion.md', 'docs/rust-prepared-provider.md'],
        ['git', 'diff', '--check'],
        ['make', 'rust-provider-check', 'PYTHON=' + str(BASE / '2026-10-24/python-live-metrics/env-312/bin/python')],
    ]
    for index, args in enumerate(commands):
        result = subprocess.run(args, cwd=SOURCE, env=os.environ | {'PYTHONDONTWRITEBYTECODE': '1'},
                                capture_output=True, text=True, timeout=120)
        (OUT / f'check-{index}.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
    record = {'status': 'pass for bounded source/inventory/MIR components', 'tests': tests,
              'checks': commands, 'new_methods': 19, 'compiler_builds': 0, 'sdk_builds': 0,
              'application_launches': 0,
              'limits': 'Literal records/refusal controls, source file facts, full-body UTF-8 fingerprints, embedding/identity and Make checks. Full application-build/prepared/launch readers, actual compiler provenance and generated runtime qualification remain open.'}
    (OUT / 'checks.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
