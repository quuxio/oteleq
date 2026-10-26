"""Validate independent Rust source-build readers without compiler builds."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
SOURCE = BASE / 'work/oteleq-rust-module-inventory'
OUT = BASE / '2026-10-26/rust-module-inventory-components-01'
MODULES = ('test_generation_rust_tools', 'test_generation_rust_protocol',
           'test_generation_rust_inventory', 'test_generation_rust_modules', 'test_generation_rust_lifetimes',
           'test_generation_rust_source_build', 'test_generation_rust_owned_build',
           'test_generation_rust_prepared', 'test_generation_rust_execution', 'test_generation_rust_session', 'test_generation_rust_telemetry',
           'test_generation_native_execution', 'test_generation_native_session',
           'test_generation_native_prepared_inputs',
           'test_generation_native_prepared_build.NativeToolchainAndSDKTests')


def check(version: str) -> dict:
    """Keep each real interpreter's original output and coverage denominator."""
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(SOURCE / 'tests')}
    data = OUT / (version + '.coverage')
    args = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--include=*/rust_tools.py,*/rust_protocol.py,*/rust_inventory.py,*/rust_modules.py,*/rust_lifetimes.py,*/rust_build_recipe.py,*/rust_source_build.py,*/rust_owned_build.py,*/rust_prepared.py,*/rust_health.py,*/rust_execution.py,*/rust_session.py,*/rust_telemetry.py,*/native_health.py,*/native_session.py',
            '-m', 'unittest', *MODULES, '-v']
    result = subprocess.run(args, cwd=SOURCE, env=env, capture_output=True, text=True, timeout=120)
    (OUT / (version + '-tests.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr[-5000:]
    count = re.search(r'Ran (\d+) tests', result.stderr)
    assert count is not None and int(count[1]) == 116 and '\nOK\n' in result.stderr
    report = OUT / (version + '-coverage.json')
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}', '-o', str(report)],
                   cwd=SOURCE, env=env, check=True, capture_output=True, timeout=30)
    files = json.loads(report.read_text())['files']
    floors = {name: value['summary'] for name, value in files.items()}
    assert len(floors) == 15 and all(value['percent_covered'] >= 80 for value in floors.values())
    return {'python': version, 'argv': args, 'test_methods': int(count[1]), 'module_coverage': floors}


def main() -> None:
    """Run bounded metadata, formatting and actual focused Make checks."""
    import ast
    original = subprocess.check_output(['git', 'show', 'da94baf4ae460bc4a4b197924e0fa0b97ca57602:adapters/generation/native_health.py'], cwd=SOURCE, text=True)
    old = {node.name: node for node in ast.parse(original).body if isinstance(node, ast.FunctionDef)}
    new = {node.name: node for node in ast.parse((SOURCE / 'adapters/generation/native_health.py').read_text()).body if isinstance(node, ast.FunctionDef)}
    def shape(node): return ast.dump(node, include_attributes=False)
    for name in ('count', 'exporter', 'lifetime'):
        assert shape(old[name]) == shape(new[name]), name
    body = old['validate'].body
    first = next(i for i, node in enumerate(body) if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'control')
    last = next(i for i in range(first, len(body)) if isinstance(body[i], ast.If))
    assert [shape(node) for node in body[first:last]] == [shape(node) for node in new['engines'].body[1:]]
    replacement = ast.parse('engines(value, pid)').body[0]
    old['validate'].body = body[:first] + [replacement] + body[last:]
    assert shape(old['validate']) == shape(new['validate'])
    import runpy
    native_session_proof = runpy.run_path(str(BASE / '2026-10-26/verify-native-session-extraction.py'))['verify'](SOURCE)
    import importlib.util
    manifest = json.loads((BASE / '2026-10-26/rust-module-inventory-source/source.json').read_text())
    spec = importlib.util.spec_from_file_location('guard', BASE / '2026-10-26/review-python-label-bound.py')
    guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    held = guard.check_source(manifest)
    OUT.mkdir(exist_ok=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tests = list(pool.map(check, ('312', '314')))
    commands = [
        ['/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustfmt', '--edition', '2021', '--check', 'src/generation.rs'],
        ['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node', str(BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),
         'README.md', 'docs/completion.md', 'docs/rust-prepared-provider.md', 'AGENTS.md'],
        ['git', 'diff', '--check'],
        ['make', 'rust-provider-check', 'PYTHON=' + str(BASE / '2026-10-24/python-live-metrics/env-312/bin/python')],
    ]
    for index, args in enumerate(commands):
        result = subprocess.run(args, cwd=SOURCE, env=os.environ | {'PYTHONDONTWRITEBYTECODE': '1'},
                                capture_output=True, text=True, timeout=120)
        (OUT / f'check-{index}.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
    record = {'status': 'pass for bounded prepared/ownership/health components', 'tests': tests,
              'checks': commands, 'new_methods': 8, 'compiler_builds': 0, 'sdk_builds': 0,
              'rust_application_launches': 0, 'harmless_python_gate_processes': 6, 'native_session_ast_proof': native_session_proof,
              'limits': 'Both standalone source-build formats, literal fixed commands/requests/channels, pre-build dependency/declaration/MIR intent, original facts and repaired-record refusals, physical boundaries, embedding/identity and Make checks. Owned-build1 original external application/gate binding and complete output denominator, exact C11 compiler records and original facts checked. Owned OS monitor and controlled Python gate exercise actual parent/group/session identity and original release/cleanup barriers. Original module/crate/source identity, physical UTF8 intervals, parent containment and unavailable routes are independently checked. Actual compiler/caller queries, private helper injection and real Rust/SDK/provider/transport/generated qualification remain open.'}
    assert guard.check_source(manifest) == held
    record['source_preservation'] = held
    record['source_head'] = manifest['head']
    (OUT / 'checks.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
