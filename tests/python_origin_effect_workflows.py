"""Literal scalar, filesystem/HTTP and current-source origin-profile qualification."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
import sys
from urllib.parse import urlsplit

import generation
import python_provider
import python_selection
from qualify_project_tests import command

SOURCE = (
    'import os\n'
    'from pathlib import Path\n'
    'from urllib.request import Request, urlopen\n'
    'counter=0\n'
    'def exercise(value:int)->int:\n'
    ' global counter\n'
    ' counter+=value\n'
    ' root=Path(os.environ["APP_DATA_DIR"])\n'
    ' data=bytes((value,255))\n'
    ' (root/"out.bin").write_bytes((root/"seed.bin").read_bytes()+data)\n'
    ' os.chmod(root/"out.bin",0o600)\n'
    ' request=Request(os.environ["APP_SERVICE_URL"]+"/observe",data=data,headers={"X-Check":"fixture"},method="POST")\n'
    ' with urlopen(request) as response:\n'
    '  if response.status!=201 or response.read()!=b"\\x00\\xff":return -1\n'
    ' return 7\n'
)

POLICY = (
    'schema_version=1\n'
    'languages=["python"]\n'
    '[generation]\n'
    'seed=123\n'
    'cases_per_function=3\n'
    '[adapters.python]\n'
    'backend="prepared"\n'
    'profile="python-native-origins-v2"\n'
    '[functions]\n'
    'include=["*exercise*"]\n'
    '[[fixtures]]\n'
    'function="*exercise*"\n'
    'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    'expected_baseline={kind="return_value",value={kind="integer",type="python.int",value="7",signed=true}}\n'
    '[[effects.filesystem]]\n'
    'name="data"\n'
    'environment="APP_DATA_DIR"\n'
    'path_mode="relative"\n'
    'files=[{path="seed.bin",hex="00ff",mode=0o600}]\n'
    'directories=["empty"]\n'
    'max_bytes=1024\n'
    'max_entries=32\n'
    'max_depth=4\n'
    '[[effects.http]]\n'
    'name="service"\n'
    'environment="APP_SERVICE_URL"\n'
    'headers=["host","x-check"]\n'
    'responses=[{status=201,hex="00ff"}]\n'
    'min_requests=1\n'
    'max_requests=1\n'
    'max_bytes=2\n'
)


def graph(value: int, counter: int, *, result: bool = False) -> dict:
    """Declare the fixture's complete scalar/list graph without the observer codec."""
    roots = {'arguments': {'ref': 0}, 'global:counter': {'type': 'int', 'value': str(counter)}}
    if result:
        roots['result'] = {'type': 'int', 'value': '7'}
    return {'roots': roots, 'nodes': [{'type': 'builtins.list', 'items': [{'type': 'int', 'value': str(value)}]}]}


def filesystem(value: int) -> dict:
    """Declare every path, byte and permission in both fixture boundaries."""
    before = [{'path_hex': '', 'kind': 'directory', 'mode': 0o700},
              {'path_hex': b'empty'.hex(), 'kind': 'directory', 'mode': 0o700},
              {'path_hex': b'seed.bin'.hex(), 'kind': 'file', 'mode': 0o600, 'hex': '00ff'}]
    output = {'path_hex': b'out.bin'.hex(), 'kind': 'file', 'mode': 0o600,
              'hex': bytes((0, 255, value, 255)).hex()}
    return {'filesystem_schema_version': 1,
            'before': {'complete': True, 'entries': before, 'gaps': []},
            'after': {'complete': True, 'entries': [*before[:2], output, before[2]], 'gaps': []}}


def check_report(path: Path, shift: int = 0, functions: int = 1) -> tuple[dict, set[str]]:
    """Check complete raw states/effects and the declared positive witness."""
    attempts = set()
    report = generation.read(path)
    assert report['source_preserved'] and (not report['blocked'])
    assert len(report['cases']) in (1, functions * 3)
    for case in report['cases']:
        assert case['exit_code'] == 0 and case['function'] in ('app.exercise', 'app.exercise_added')
        value, = case['arguments']
        assert type(value) is int and 0 <= value <= 7
        bundle = generation.read(path.parent / case['case'] / 'typed-bundle.json')['cases'][0]
        for lane in ('baseline', 'instrumented_on'):
            assert len(bundle[lane]) == 2
            for index, observed in enumerate(bundle[lane]):
                folder = path.parent / case['case'] / (lane + '-' + str(index))
                attempts.add(str(folder))
                assert python_provider.same(generation.read(folder / 'observation'), {'before': graph(value, 0), 'after': graph(value, value + shift), 'outcome': {'kind': 'return', 'value': graph(value, value + shift, result=True)}})
                execution = observed['execution']
                assert execution['capture_complete'] is True and execution['termination'] == {'kind': 'exit', 'code': 0}
                assert execution['channels']['stdout'] == execution['channels']['stderr'] == []
                fs = json.loads(bytes(execution['channels']['filesystem:data']))
                assert python_provider.same(fs, filesystem(value))
                http = json.loads(bytes(execution['channels']['http:service']))
                assert http['complete'] is True and (not http['gaps']) and (len(http['requests']) == 1)
                request = http['requests'][0]
                assert request['method'] == 'POST' and request['target_hex'] == b'/observe'.hex() and (request['version'] == 'HTTP/1.1')
                assert request['body_hex'] == bytes((value, 255)).hex() and request['response_index'] == 0
                assert bytes.fromhex(request['response_hex']) == b'HTTP/1.1 201 Fixture\r\nConnection: close\r\nContent-Length: 2\r\n\r\n\x00\xff'
                binding = generation.read(folder / 'http-controls.json')['environment']['APP_SERVICE_URL']
                headers = [bytes.fromhex(line) for line in request['header_lines_hex']]
                assert len(headers) == 2
                assert [h.partition(b':')[2].strip() for h in headers if h.partition(b':')[0].lower() == b'host'] == [urlsplit(binding).netloc.encode()]
                assert [h.partition(b':')[2].strip() for h in headers if h.partition(b':')[0].lower() == b'x-check'] == [b'fixture']
                origin = generation.read(folder / 'python-verified-origins.json')
                assert len(origin['selected']) == 1 and origin['selected'][0]['qualname'] == case['function'].split('.', 1)[1]
                if lane == 'instrumented_on':
                    witness = execution['witness']
                    assert witness['functions'] == {case['function']: 1} and witness['spans'] == 1 and (witness['pending'] == 0) and (not any(witness['losses'].values()))
                else:
                    assert execution['witness'] is None
    return (report, attempts)


def stage_source(stage: str) -> str:
    """Expected current bodies are declared here, independently of app output."""
    if stage in ('direct', 'export', 'promoted-unchanged'):
        return SOURCE
    changed = SOURCE.replace('counter+=value\n', 'counter+=value+1\n')
    if stage == 'promoted-changed-body':
        return changed
    assert stage == 'promoted-added-function'
    return changed + '\n' + changed[changed.index('def exercise('):].replace('def exercise(', 'def exercise_added(', 1)


def selection_builder(text: str):
    """Bind literal source and AST declaration lines to prelaunch file facts."""
    functions = {node.name: node.lineno for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)}
    def expected(folder: Path, entry: dict) -> tuple:
        facts = generation.read(folder / 'python-expected-origins.json')
        assert facts['python_hexversion'] == sys.hexversion and facts['optimisation'] == 0
        assert entry['path'] == 'app.py' and entry['name'] in functions
        assert entry['line'] == functions[entry['name']] and 'receiver_fixture' not in entry
        assert len(facts['selected']) == 1
        row = facts['selected'][0]
        path = folder / 'project/app.py'
        assert row['path_hex'] == os.fsencode(path).hex()
        assert row['sha256'] == hashlib.sha256(text.encode()).hexdigest()
        assert (row['qualname'], row['line']) == (entry['name'], functions[entry['name']])
        source = python_selection.Source(os.fsencode(path), text.encode(), row['device'], row['inode'], row['mtime_ns'], row['mode'])
        return facts, (python_selection.Selection(source, entry['name'], functions[entry['name']]),)
    return expected


def run(cli: Path, provider: Path, folder: Path) -> None:
    """Exercise independent effects and fresh source discovery through real CLI operations."""
    folder.mkdir(mode=0o700)
    source = folder / 'application'
    source.mkdir()
    (source / 'app.py').write_text(SOURCE)
    config = folder / 'equivalence.toml'
    config.write_text(POLICY)
    workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
        '--workspace-parent', folder, '--config', config], folder, 'plan'))
    data = generation.read(workspace / 'plan.json')
    assert len([row for row in data['inventory'] if row['status'] == 'ready']) == 1
    assert not any(row['status'] == 'blocked' for row in data['inventory'])
    command([cli, 'generate', '--workspace', workspace], folder, 'generate')
    command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'], folder, 'run')
    check_report(folder / 'comparison/report.json')
    exported = folder / 'exported'
    command([cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'], folder, 'export')
    command([cli, 'run', '--workspace', exported, '--report-dir', folder / 'export-comparison'], folder, 'export-run')
    check_report(folder / 'export-comparison/report.json')
    promoted = source / 'equivalence-tests'
    command([cli, 'promote', '--workspace', workspace, '--source', source,
        '--destination', promoted, '--apply'], folder, 'promote')
    try:
        for stage in ('promoted-unchanged', 'promoted-changed-body', 'promoted-added-function'):
            (source / 'app.py').write_text(stage_source(stage))
            command([sys.executable, '-I', '-B', promoted / 'test_equivalence.py'], folder, stage, 0,
                {'OTELEQ_SOURCE': str(source), 'OTELEQ_WORKSPACE_PARENT': str(folder)})
    finally:
        (source / 'app.py').write_text(SOURCE)


def retained(folder: Path, cli: Path, provider: Path, catalogue: dict,
             interpreter: dict, recheck_attempt) -> dict:
    """Audit all 72 actual attempts without re-executing target applications."""
    expected_ops = {'plan', 'generate', 'run', 'export', 'export-run', 'promote',
                    'promoted-unchanged', 'promoted-changed-body', 'promoted-added-function'}
    assert {path.stem for path in folder.glob('*.exit')} == expected_ops
    for name in expected_ops:
        assert (folder / (name + '.exit')).read_text() == '0\n'
        assert generation.read(folder / (name + '.started.json'))['expected_exit'] == 0
    reports = [('direct', folder / 'comparison/report.json'), ('export', folder / 'export-comparison/report.json')]
    for stage in ('promoted-unchanged', 'promoted-changed-body', 'promoted-added-function'):
        records = [json.loads(line) for line in (folder / (stage + '.stdout')).read_text().splitlines()]
        functions = 2 if stage == 'promoted-added-function' else 1
        assert len(records) == functions * 3 + 1
        workspace = Path(records[0]['workspace'])
        assert workspace.is_relative_to(folder)
        data = generation.read(workspace / 'plan.json')
        assert len([row for row in data['inventory'] if row['status'] == 'ready']) == functions
        reports.extend((stage, Path(row['report'])) for row in records[1:])
    attempts, identities, requested = set(), [], {}
    comparisons = 0
    for stage, path in reports:
        assert path.is_relative_to(folder)
        functions = 2 if stage == 'promoted-added-function' else 1
        shift = int(stage in ('promoted-changed-body', 'promoted-added-function'))
        report, observed = check_report(path, shift, functions)
        assert attempts.isdisjoint(observed)
        attempts |= observed
        entries = {entry['otelc_function']: entry for entry in report['inventory']}
        selected = selection_builder(stage_source(stage))
        for case in report['cases']:
            requested.setdefault((stage, case['function']), []).append(case['arguments'][0])
            bundle = path.parent / case['case'] / 'typed-bundle.json'
            result = subprocess.run([str(cli), 'compare-observations', str(bundle)], capture_output=True, check=False, timeout=30)
            assert result.returncode == 0 and json.loads(result.stdout) == case['comparison']
            comparisons += 1
            for lane in ('baseline', 'instrumented_on'):
                for index in range(2):
                    identities.append(recheck_attempt(path.parent / case['case'] / (lane + '-' + str(index)),
                        entries[case['function']], provider, catalogue, interpreter, selection_builder=selected))
    assert len(attempts) == len(identities) == 72
    assert all(len(values) == len(set(values)) == 3 for values in requested.values())
    assert len({row['runtime'] for row in identities}) == len(identities)
    assert (folder / 'application/app.py').read_text() == SOURCE
    return {'actual_application_launches': 72, 'sdk_processes': 36,
        'reports': len(reports), 'generated_domain_cases_per_function': 3,
        'complete_raw_and_typed_observations': 72, 'recomputed_comparisons': comparisons,
        'complete_raw_graphs_and_effect_oracles': True, 'source_restored': True,
        'scope': 'Scalar domains, global mutations, literal filesystem bytes/kinds/modes and scripted HTTP, exported suites and current-source promotion through unchanged/changed/added-source stages.'}
