"""First actual CLI generated/exported native-project smoke, with independent roots."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

OUTPUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-21/native-public-smoke-61b1a09-58abcf5')
SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-workflow')
PROVIDER = Path('/Users/sclarke/github/otelc-qualification/2026-10-21/native-main-transform/58abcf5/provider')
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
    expected_before, expected_after = {}, {}
    for item in entry['globals']:
        initial = 7 if item['name'] == 'total' else 3 if item['unit'] == entry['unit'] else 4
        node = {'kind': 'integer', 'type': entry['language']+'.int', 'value': str(initial), 'bits': 32, 'signed': True}
        expected_before['global:'+item['name']] = node
        expected_after['global:'+item['name']] = {**node, 'value': str(initial+5)}
    assert len(expected_before) == 3
    returned = {'kind':'integer','type':entry['language']+'.int','value':'24','bits':32,'signed':True}
    summary = json.loads((report/'report.json').read_text())
    assert summary['source_preserved'] and not summary['blocked'] and len(summary['cases']) == 1
    record = summary['cases'][0]
    assert record['exit_code'] == 0 and record['arguments'] == [5]
    bundle = json.loads((report/record['case']/'typed-bundle.json').read_text())['cases'][0]
    assert set(bundle['contract']['required_roots']) == set(expected_before)
    checked=[]
    for lane in ('baseline','instrumented_on'):
        assert len(bundle[lane]) == 2
        for index, attempt in enumerate(bundle[lane]):
            observation=attempt['observation']
            assert observation['gaps'] == []
            assert observation['before'] == {'roots':expected_before,'nodes':[]}
            assert observation['after'] == {'roots':expected_after,'nodes':[]}
            assert observation['outcome'] == {'kind':'return','graph':{'roots':{**expected_after,'result':returned},'nodes':[]}}
            execution=attempt['execution']
            assert execution['channels'] == {'stdout':[],'stderr':[]} and execution['capture_complete'] is True
            assert execution['termination'] == {'kind':'exit','code':0}
            if lane == 'baseline':
                assert execution['witness'] is None
            else:
                witness=execution['witness']
                assert witness['functions'] == {entry['otelc_function']:1} and witness['spans'] == 1
                assert witness['pending'] == 0 and not any(witness['losses'].values())
            folder=report/record['case']/(lane+'-'+str(index))
            lines=(folder/'observation').read_bytes().splitlines()
            abi=json.loads(lines[0][4:])
            assert abi['char_bits']==8 and abi['bits']['int']==32 and abi['byte_order']=='little'
            assert lines[1]==b'before' and lines[6]==b'after'
            for position,item in enumerate(entry['globals']):
                prefix=(item['name']+':int:').encode()
                for row,expected in ((lines[2+position],expected_before),(lines[7+position],expected_after)):
                    assert row.startswith(prefix)
                    bits=bytes.fromhex(row[len(prefix):].decode())
                    assert len(bits)==4 and str(int.from_bytes(bits,'little',signed=True))==expected['global:'+item['name']]['value']
            assert lines[5]==b'return:int:18000000'
            checked.append(str(folder))
    write(report/'independent-oracle.json',{'checked_actual_attempts':checked,'all_complete_roots_results_channels_and_witnesses_match':True})
    return len(checked)


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
                      'observations': count, 'scope': 'actual native project CLI smoke with complete independent typed/raw scalar oracles'})
write(OUTPUT / 'summary.json', {'runtime_head': '61b1a091fdf26824e8b652f66922bae6b7b76b86',
    'cli_sha256': digest(CLI), 'provider_head': '58abcf523cfe941ae349d8f6e4c6bf56c1295243', 'languages': summaries})
print('Both native project CLI generated and detached-export routes completed; raw typed observations retained')
