"""Preserve the complete candidate source while running bounded component gates."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--methods', type=int, required=True)
args = parser.parse_args()
root, out = args.root.resolve(strict=True), args.output.resolve()
out.mkdir()
base = Path('/Users/sclarke/github/oteleq-qualification')
names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                                cwd=root).decode().strip('\0').split('\0')


def facts():
    result = {}
    for name in names:
        path = root / name
        info = path.lstat()
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result[name] = [digest, info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                        info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink]
    return result


before, checks = facts(), []
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
    PYTHONPATH=os.pathsep.join(str(root / name) for name in ('adapters/generation', 'examples', 'tests')),
    OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang', OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++',
    NODE_PATH=str(base / 'work/oteleq-native-generated/ci/markdownlint/node_modules'))


def run(label, arguments):
    tick = time.monotonic()
    with (out / (label + '.log')).open('wb') as stream:
        result = subprocess.run(arguments, cwd=root, env=environment, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=60)
    checks.append(dict(label=label, argv=arguments, returncode=result.returncode,
                       seconds=time.monotonic() - tick))
    (out / 'status.json').write_text(json.dumps({'checks': checks,
        'status': 'failed' if result.returncode else 'running'}, indent=2) + '\n')
    print(label, result.returncode, flush=True)
    assert result.returncode == 0, label


for version in ('312', '314'):
    python = str(base / f'2026-10-24/python-live-metrics/env-{version}/bin/python')
    run(version, ['make', 'native-metric-control-check', 'PYTHON=' + python])
    shutil.copyfile(root / '.native-metric-control.coverage', out / (version + '.coverage'))
    log = (out / (version + '.log')).read_text()
    assert f'Ran {args.methods} tests' in log and '... skipped ' not in log

compatibility = ['test_generation_native_lifetime_policy', 'test_generation_native_lifetime_frontend',
    'test_generation_native_lifetime_run', 'test_generation_makefile', 'test_generation_policy',
    'test_generation_sequences.SequenceTests.test_malformed_schedules_and_unavailable_requested_adapters_refuse',
    'test_generation_sequences.SequenceTests.test_go_calls_require_source_provider_and_complete_live_states']
python = str(base / '2026-10-24/python-live-metrics/env-312/bin/python')
run('compatibility', [python, '-m', 'unittest', *compatibility, '-v'])
node = '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
run('examples', ['make', 'examples', 'PYTHON=' + python, 'NODE=' + node])
run('markdown', [node, str(base / 'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),
                 '**/*.md', '--ignore', 'ci/markdownlint/node_modules/**'])
run('rustfmt', ['/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustfmt',
               '--edition', '2021', '--check', 'src/generation.rs'])
run('diff', ['git', 'diff', '--check'])
assert facts() == before
result = {'status': 'pass', 'head_before_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
    cwd=root, text=True).strip(), 'source_files': len(names), 'source_facts': before, 'checks': checks,
    'methods_per_python': args.methods, 'sdk_builds': 0, 'compiler_builds': 0, 'native_application_launches': 0,
    'syntax_translation_units': 8,
    'scope': 'Literal/mocked native SDK and raw OTLP, strict Clang syntax, compatibility mocks and stock Python command children only',
    'limits': ['No genuine SDK application or retained-workflow qualification',
               'Full local make check not started below12GiB start margin']}
(out / 'status.json').write_text(json.dumps(result, indent=2) + '\n')
print('PASS', len(names), flush=True)
