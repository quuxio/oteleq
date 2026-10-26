"""First actual CLI generated/exported native-project smoke, with independent roots."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

OUTPUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-21/native-public-smoke-3ce1cc5')
SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-workflow')
PROVIDER = Path('/Users/sclarke/github/otelc-qualification/2026-10-21/native-main-transform/dc4f07a/provider')
PYTHON = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider/.venv/bin/python')
OUTPUT.mkdir(exist_ok=False)
CLI = OUTPUT / 'quux-oteleq'
shutil.copy2('/Users/sclarke/github/oteleq-qualification/work/native-workflow-target/debug/quux-oteleq', CLI)
CLI.chmod(0o555)
environment = {**os.environ, 'OTELEQ_PYTHON': str(PYTHON), 'PYTHONDONTWRITEBYTECODE': '1',
    'OTELC_CLANG': '/opt/homebrew/opt/llvm@22/bin/clang', 'OTELC_CLANGXX': '/opt/homebrew/opt/llvm@22/bin/clang++'}


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def digest(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def command(arguments, folder):
    folder.mkdir()
    argv = [str(CLI), *map(str, arguments)]
    write(folder / 'command.json', argv)
    result = subprocess.run(argv, cwd=OUTPUT, env=environment, capture_output=True, timeout=600, check=False)
    (folder / 'stdout').write_bytes(result.stdout)
    (folder / 'stderr').write_bytes(result.stderr)
    write(folder / 'exit.json', result.returncode)
    if result.returncode:
        raise ValueError('public command failed: ' + str(folder))
    return result.stdout.decode().strip()


def oracle(workspace, report):
    plan = json.loads((workspace / 'plan.json').read_text())
    entry = next(item for item in plan['inventory'] if item['status'] == 'ready')
    records = list(report.rglob('typed-observation.json'))
    assert len(records) == 4, ('actual repeat count', len(records))
    for path in records:
        record = json.loads(path.read_text())
        # Typed observation shape is retained verbatim for the fuller oracle.
        write(path.with_name('independent-input.json'), {'arguments': [5], 'expected_result': 24,
            'expected_source_roots': entry['globals'], 'raw_observation': record})
    return len(records)


summaries = []
for language in ('c', 'cpp'):
    base = OUTPUT / language
    source = base / 'source'
    for name in ('src', 'include', 'build/generated'):
        (source / name).mkdir(parents=True)
    (base / 'workspaces').mkdir()
    extension = '.cpp' if language == 'cpp' else '.c'
    compiler = '/opt/homebrew/opt/llvm@22/bin/' + ('clang++' if language == 'cpp' else 'clang')
    (source / 'include/state.h').write_text('extern int total;int sibling(int);\n')
    (source / 'build/generated/settings.h').write_text('#define OFFSET 4\n')
    units = ['src/one' + extension, 'src/two' + extension]
    (source / units[0]).write_text('#include "state.h"\n#include "settings.h"\nstatic int local=3;\n'
        'int selected(int value){local+=value;return sibling(value)+local+OFFSET;}int main(void){}\n')
    (source / units[1]).write_text('#include "state.h"\nint total=7;static int local=4;\n'
        'int sibling(int value){local+=value;total+=value;return total;}\n')
    database = [{'directory': str(source / 'build'), 'file': '../' + name,
        'arguments': [compiler, '-I', '../include', '-I', 'generated', '-std=c++17' if language == 'cpp' else '-std=c11',
                      '-O0', '-c', '../' + name, '-o', str(index) + '.o']} for index, name in enumerate(units)]
    (source / 'build/compile_commands.json').write_text(json.dumps(database))
    original = {path.relative_to(source).as_posix(): digest(path) for path in source.rglob('*') if path.is_file()}
    selected = 'selected(int)' if language == 'cpp' else 'selected'
    config = base / 'equivalence.toml'
    config.write_text('languages=[' + json.dumps(language) + ']\n[functions]\ninclude=[' + json.dumps(selected) + ']\n'
        '[[fixtures]]\nfunction=' + json.dumps(selected) + '\ncases=[[5]]\n'
        '[adapters.' + language + ']\ncompilation_database="build/compile_commands.json"\n'
        '[[adapters.' + language + '.targets]]\nname="application"\nunits=[' +
        ','.join('{source=' + json.dumps(name) + '}' for name in units) + ']\n')
    workspace = Path(command(['plan', '--source', source, '--otelc-root', PROVIDER, '--workspace-parent', base / 'workspaces',
                              '--config', config], base / 'plan'))
    command(['generate', '--workspace', workspace], base / 'generate')
    generated = json.loads(command(['run', '--workspace', workspace, '--report-dir', base / 'generated-report'], base / 'run'))
    assert generated['exit_code'] == 0
    assert {path.relative_to(source).as_posix(): digest(path) for path in source.rglob('*') if path.is_file()} == original
    count = oracle(workspace, base / 'generated-report')
    exported = base / 'exported'
    command(['export-tests', '--workspace', workspace, '--destination', exported, '--apply'], base / 'export')
    shutil.rmtree(source)
    detached = json.loads(command(['run', '--workspace', exported, '--report-dir', base / 'exported-report'], base / 'detached'))
    assert detached['exit_code'] == 0
    count += oracle(exported, base / 'exported-report')
    summaries.append({'language': language, 'workspace': str(workspace), 'exported': str(exported),
                      'observations': count, 'scope': 'first CLI smoke; fuller independent oracle still required'})
write(OUTPUT / 'summary.json', {'runtime_head': '3ce1cc591d3df9169f77b901720189fb138756fe',
    'cli_sha256': digest(CLI), 'provider_head': 'dc4f07a9c4c72103d0defa3486bf07e038c471d7', 'languages': summaries})
print('Both native project CLI generated and detached-export routes completed; raw typed observations retained')
