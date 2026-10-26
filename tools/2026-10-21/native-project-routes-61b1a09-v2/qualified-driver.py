"""Qualify explicit native targets, complete scalar state and detached/reduced suites."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from qualify_generation import command

CASES = (('c-o0', 'c', '-O0', False), ('cpp-o2', 'cpp', '-O2', False), ('c-state', 'c', '-O2', True))


def digest(path: Path) -> str:
    """Retain actual original fixture bytes independently of the generated plan."""
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def write(path: Path, value: object) -> None:
    """Qualification records are separate from the application's generated suite."""
    path.write_text(json.dumps(value, indent=2) + '\n')


def prepare(cli: Path, provider: Path, folder: Path, language: str, optimisation: str,
            difference: bool = False, *, opaque: bool = False) -> tuple[Path, Path, dict]:
    """Both lanes compile the same declared two-unit fixture and generated header."""
    source = folder / 'source'
    for name in ('src', 'include', 'build/generated'):
        (source / name).mkdir(parents=True)
    extension = '.cpp' if language == 'cpp' else '.c'
    compiler = os.environ.get('OTELC_CLANGXX' if language == 'cpp' else 'OTELC_CLANG')
    if compiler is None:
        prefix = '/opt/homebrew/opt/llvm@22/bin/' if sys.platform == 'darwin' else '/usr/lib/llvm-22/bin/'
        compiler = prefix + ('clang++' if language == 'cpp' else 'clang')
    (source / 'include/state.h').write_text('extern int total;int sibling(int);\n')
    (source / 'build/generated/settings.h').write_text('#define OFFSET 4\n')
    units = ['src/one' + extension, 'src/two' + extension]
    (source / units[0]).write_text('#include "state.h"\n#include "settings.h"\n#include <stdlib.h>\n'
        '#if __has_include("optional.h")\n#define EXTRA 1\n#else\n#define EXTRA 0\n#endif\n'
        'static int local=3;int selected(int amount){local+=amount;int result=sibling(amount)+local+OFFSET+EXTRA;'
        + ('if(getenv("OTELC_CONFIG"))total++;' if difference else '') + 'return result;}int main(void){}\n')
    (source / units[1]).write_text('#include "state.h"\nint total=7;static int local=4;\n'
        'int sibling(int amount){local+=amount;total+=amount;return total;}\n' +
        ('volatile int hidden=1;\n' if opaque else ''))
    database = [{'directory': str(source / 'build'), 'file': '../' + name,
        'arguments': [compiler, '-I', '../include', '-I', 'generated',
                      '-std=c++17' if language == 'cpp' else '-std=c11', optimisation,
                      '-c', '../' + name, '-o', str(index) + '.o']} for index, name in enumerate(units)]
    (source / 'build/compile_commands.json').write_text(json.dumps(database))
    original = {path.relative_to(source).as_posix(): digest(path) for path in source.rglob('*') if path.is_file()}
    function = 'selected(int)' if language == 'cpp' else 'selected'
    config = folder / 'equivalence.toml'
    config.write_text('languages=[' + json.dumps(language) + ']\n[functions]\ninclude=[' + json.dumps(function) + ']\n'
        '[[fixtures]]\nfunction=' + json.dumps(function) + '\ncases=[[5]]\n'
        'domains=[{kind="integer",minimum=0,maximum=5}]\n'
        '[adapters.' + language + ']\ncompilation_database="build/compile_commands.json"\n'
        '[[adapters.' + language + '.targets]]\nname="application"\nunits=[' +
        ','.join('{source=' + json.dumps(name) + '}' for name in units) + ']\n')
    workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
                              '--workspace-parent', folder, '--config', config], folder, 'plan'))
    command([cli, 'generate', '--workspace', workspace], folder, 'generate')
    return workspace, source, original


def scalar(language: str, value: int) -> dict:
    """The fixture requires the recorded 32-bit signed native integer ABI."""
    return {'kind': 'integer', 'type': language + '.int', 'value': str(value), 'bits': 32, 'signed': True}


def check_report(path: Path, *, difference: bool = False) -> tuple[int, dict]:
    """Every actual repeat has independently expected complete state and witnesses."""
    report = json.loads(path.read_text())
    assert report['source_preserved'] and not report['blocked'] and len(report['cases']) == 1
    result = report['cases'][0]
    assert result['exit_code'] == int(difference)
    entry = next(item for item in report['inventory'] if item['status'] == 'ready')
    amount = result['arguments'][0]
    bundle = json.loads((path.parent / result['case'] / 'typed-bundle.json').read_text())['cases'][0]
    assert len(entry['globals']) == 3 and len({item['unit'] for item in entry['globals']}) == 2
    initial = {'global:' + item['name']: scalar(entry['language'],
        7 if item['name'] == 'total' else 3 if item['unit'] == entry['unit'] else 4) for item in entry['globals']}
    assert set(bundle['contract']['required_roots']) == set(initial)
    launches = 0
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        after = {name: scalar(entry['language'], int(node['value']) + amount +
                 int(difference and lane == 'instrumented_on' and name == 'global:total'))
                 for name, node in initial.items()}
        outcome = {'kind': 'return', 'graph': {'roots': {**after,
                   'result': scalar(entry['language'], 14 + 2 * amount)}, 'nodes': []}}
        for index, attempt in enumerate(bundle[lane]):
            observation = attempt['observation']
            assert not observation['gaps'] and observation['before'] == {'roots': initial, 'nodes': []}
            assert observation['after'] == {'roots': after, 'nodes': []} and observation['outcome'] == outcome
            execution = attempt['execution']
            assert execution['channels'] == {'stdout': [], 'stderr': []} and execution['capture_complete']
            assert execution['termination'] == {'kind': 'exit', 'code': 0}
            if lane == 'baseline':
                assert execution['witness'] is None
            else:
                witness = execution['witness']
                assert witness['functions'] == {result['function']: 1} and witness['spans'] == 1
                assert witness['pending'] == 0 and not any(witness['losses'].values())
            folder = path.parent / result['case'] / (lane + '-' + str(index))
            lines = (folder / 'observation').read_bytes().splitlines()
            abi = json.loads(lines[0][4:])
            assert abi['char_bits'] == 8 and abi['bits']['int'] == 32 and abi['byte_order'] == 'little'
            assert lines[1] == b'before' and lines[6] == b'after'
            for position, item in enumerate(entry['globals']):
                prefix = (item['name'] + ':int:').encode()
                for row, expected in ((lines[2 + position], initial), (lines[7 + position], after)):
                    assert row.startswith(prefix)
                    raw = bytes.fromhex(row[len(prefix):].decode())
                    assert len(raw) == 4 and str(int.from_bytes(raw, 'little', signed=True)) == expected['global:' + item['name']]['value']
            assert lines[5] == b'return:int:' + (14 + 2 * amount).to_bytes(4, 'little', signed=True).hex().encode()
            launches += 1
    return launches, report


def framework(workspace: Path, folder: Path, name: str, *, difference: bool) -> int:
    """The generated standard-library unittest must return the declared verdict."""
    output = command([sys.executable, workspace / 'tests/test_equivalence.py'], folder, name,
                     expected=int(difference))
    summaries = [json.loads(line) for line in output.splitlines()]
    assert len(summaries) == 1
    return check_report(Path(summaries[0]['report']), difference=difference)[0]


def refusals(cli: Path, provider: Path, folder: Path) -> int:
    """Changed inputs, probes and retained context refuse before application launch."""
    folder.mkdir()
    workspace, source, original = prepare(cli, provider, folder, 'c', '-O0')
    header = source / 'build/generated/settings.h'
    saved = header.read_bytes()
    header.write_text('#define OFFSET 9\n')
    command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'changed'], folder, 'changed-header', expected=4)
    header.write_bytes(saved)
    optional = source / 'build/generated/optional.h'
    optional.write_text('existence-only input\n')
    command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'probe'], folder, 'new-probe', expected=4)
    optional.unlink()
    assert {path.relative_to(source).as_posix(): digest(path) for path in source.rglob('*') if path.is_file()} == original
    metadata = next((workspace / 'native-context/c/units').glob('*/metadata.json'))
    metadata.write_text('{}')
    command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'metadata'], folder, 'changed-metadata', expected=4)
    command([cli, 'clean', '--workspace', workspace], folder, 'preserve-edited-context', expected=4)
    assert workspace.exists()
    assert not any(path.parent.name.startswith(('baseline-', 'instrumented_on-')) for path in folder.rglob('command.json'))
    return 4


def main() -> None:
    """Run external diagnostic qualification; preserve every real launch and source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    args = parser.parse_args()
    provider, supplied_cli = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True)
    folder = args.report_dir.resolve()
    if any(folder.is_relative_to(root) for root in (provider, Path(__file__).resolve().parents[1])):
        parser.error('qualification directory must be new and external')
    folder.mkdir(mode=0o700, exist_ok=False)
    cli = folder / 'quux-oteleq'
    shutil.copy2(supplied_cli, cli)
    cli.chmod(0o555)
    os.environ['OTELEQ_PYTHON'], os.environ['OTELEQ_CLI'] = sys.executable, str(cli)
    launches, reduced, results = 0, False, []
    for name, language, optimisation, difference in CASES:
        case = folder / name
        case.mkdir()
        workspace, source, original = prepare(cli, provider, case, language, optimisation, difference)
        captures = case / 'comparison'
        command([cli, 'run', '--workspace', workspace, '--report-dir', captures], case, 'run', expected=int(difference))
        count, report = check_report(captures / 'report.json', difference=difference)
        count += framework(workspace, case, 'generated-framework', difference=difference)
        target = report['cases'][0]['case']
        replay = json.loads(command([cli, 'replay', '--workspace', workspace, '--case', target], case, 'replay', expected=int(difference)))
        count += check_report(Path(replay['report']), difference=difference)[0]
        exported = case / 'exported'
        command([cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'], case, 'export')
        assert {path.relative_to(source).as_posix(): digest(path) for path in source.rglob('*') if path.is_file()} == original
        shutil.rmtree(source)
        count += framework(exported, case, 'detached-framework', difference=difference)
        if difference:
            shrink = case / 'shrinking'
            command([cli, 'shrink', '--workspace', exported, '--case', target, '--report-dir', shrink, '--trials', '8'], case, 'shrink', expected=1)
            result = json.loads((shrink / 'shrink.json').read_text())
            assert result['original_arguments'] == [5] and result['reduced_arguments'] == [0]
            assert result['status'] == 'candidate_rule_minimal' and result['source_preserved']
            reports = [shrink / 'original/report.json', shrink / 'confirmation/report.json',
                       *(Path(trial['report']) for trial in result['trials'])]
            count += sum(check_report(path, difference=True)[0] for path in reports)
            count += framework(Path(result['workspace']), case, 'reduced-framework', difference=True)
            reduced = True
        launches += count
        results.append({'name': name, 'language': language, 'optimisation': optimisation,
                        'verdict': 'different_observed' if difference else 'equivalent_observed',
                        'actual_application_launches': count})
    controls = refusals(cli, provider, folder / 'refusals')
    actual = [path for path in folder.rglob('command.json') if path.parent.name.startswith(('baseline-', 'instrumented_on-'))
              and 'original' not in path.relative_to(folder).parts]
    # The original shrink replay is copied evidence, rather than new launches.
    assert len(actual) == launches, (len(actual), launches)
    write(folder / 'qualification.json', {'claim': 'equivalence over these tests and observations',
        'artefact_class': 'diagnostic', 'runtime_cli_sha256': digest(cli),
        'qualifier_sha256': digest(Path(__file__)), 'cases': results, 'actual_application_launches': launches,
        'refusal_controls': controls, 'generated_detached_replay_and_scalar_reduction': reduced,
        'source_preserved': True, 'scope': 'declared signed integer free functions in explicit same-language native targets; macOS ARM64 provider execution'})
    print(json.dumps({'actual_application_launches': launches, 'refusal_controls': controls}))


if __name__ == '__main__':
    main()
