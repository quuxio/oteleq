"""Qualify ordinary cache decisions and source fallback with complete literal oracles."""

import argparse
import json
import os
from pathlib import Path
import py_compile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import python_inputs
import python_provider
import qualify_python_generated_origins as origins
from python_cache_qualification import CacheInputs
from qualify_project_tests import command

SOURCE = ('counter=0\ndef workload(value:int)->int:\n global counter\n counter+=value\n return value*2+3\n')
CHANGED = SOURCE.replace('value*2+3', 'value*2+4')
TIME = 1_700_000_000_123456789
MODES = ('timestamp', 'checked', 'unchecked', 'missing', 'stale-timestamp', 'stale-checked',
         'older-unchecked', 'invalid-magic')
INVALIDATION = {'timestamp': py_compile.PycInvalidationMode.TIMESTAMP,
                'checked': py_compile.PycInvalidationMode.CHECKED_HASH,
                'unchecked': py_compile.PycInvalidationMode.UNCHECKED_HASH}
FALLBACK = {'missing', 'stale-timestamp', 'stale-checked', 'invalid-magic'}


def literal_source(mode: str) -> str:
    """The accepted older unchecked cache is deliberately different from current source."""
    assert mode in MODES
    return CHANGED if mode.startswith(('stale-', 'older-')) else SOURCE


def expected_result(mode: str) -> int:
    """Only invalidated caches fall back to the changed body."""
    assert mode in MODES
    return 18 if mode.startswith('stale-') else 17


def policy(mode: str) -> str:
    """Declare one fixed input and an independent expected scalar return."""
    return ('schema_version=1\nlanguages=["python"]\n[generation]\nseed=123\ncases_per_function=1\n'
        '[adapters.python]\nbackend="prepared"\nprofile="python-native-cache-origins-v3"\n'
        '[functions]\ninclude=["*workload*"]\n[[fixtures]]\nfunction="*workload*"\ncases=[[7]]\n'
        'expected_baseline={kind="return_value",value={kind="integer",type="python.int",value="'
        + str(expected_result(mode)) + '",signed=true}}\n[limits]\ncase_timeout_ms=30000\n')


def prepare(folder: Path, mode: str, cli: Path, provider: Path) -> tuple[Path, CacheInputs]:
    """Create ordinary cache inputs, then freeze all independent facts before planning."""
    folder.mkdir(mode=0o700)
    source = folder / 'application'; source.mkdir()
    target = source / 'target.py'; target.write_text(SOURCE); os.utime(target, ns=(TIME, TIME))
    kind = mode.removeprefix('stale-').removeprefix('older-')
    if kind != 'missing':
        compiled = Path(py_compile.compile(str(target), doraise=True,
            invalidation_mode=INVALIDATION['timestamp' if kind == 'invalid-magic' else kind]))
        if mode.startswith(('stale-', 'older-')):
            target.write_text(CHANGED)
            updated = TIME + 2_000_000_000 if mode == 'stale-timestamp' else TIME
            os.utime(target, ns=(updated, updated))
        elif mode == 'invalid-magic':
            compiled.write_bytes(b'BAD!' + compiled.read_bytes()[4:])
    inputs = CacheInputs.capture(source, {'target.py': literal_source(mode).encode()})
    generation.write(folder / 'independent-inputs.json', inputs.receipt())
    configuration = folder / 'equivalence.toml'; configuration.write_text(policy(mode))
    workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
        '--workspace-parent', folder, '--config', configuration], folder, 'plan'))
    inputs.verify_workspace(workspace)
    plan = generation.read(workspace / 'plan.json')
    assert len([e for e in plan['inventory'] if e['status'] == 'ready']) == 1
    assert not any(e['status'] == 'blocked' for e in plan['inventory'])
    command([cli, 'generate', '--workspace', workspace], folder, 'generate')
    return workspace, inputs


def scalar(value: int) -> dict:
    return {'kind': 'integer', 'type': 'python.int', 'value': str(value), 'signed': True, 'bits': None}


def raw_graph(counter: int, result: int | None = None) -> dict:
    roots = {'arguments': {'ref': 0}, 'global:counter': {'type': 'int', 'value': str(counter)}}
    if result is not None:
        roots['result'] = {'type': 'int', 'value': str(result)}
    return {'roots': roots, 'nodes': [{'type': 'builtins.list', 'items': [{'type': 'int', 'value': '7'}]}]}


def typed_graph(counter: int, result: int | None = None) -> dict:
    roots = {'arguments': {'kind': 'reference', 'node_id': 'n0'}, 'global:counter': scalar(counter)}
    if result is not None:
        roots['result'] = scalar(result)
    return {'roots': roots, 'nodes': [{'id': 'n0', 'type': 'python.builtins.list', 'fields': {'item:0': scalar(7)}}]}


def check_report(path: Path, mode: str) -> int:
    """Require full raw and typed graphs, fixed input and an independent return oracle."""
    report = generation.read(path)
    assert report['source_preserved'] and not report['blocked'] and len(report['cases']) == 1
    case = report['cases'][0]
    assert case['exit_code'] == 0 and case['function'] == 'target.workload' and case['arguments'] == [7]
    bundle = generation.read(path.parent / case['case'] / 'typed-bundle.json')['cases'][0]
    contract = bundle['contract']; result = expected_result(mode)
    assert set(contract['required_roots']) == {'arguments', 'global:counter'}
    assert contract['expected_baseline'] == {'kind': 'return_value', 'value': scalar(result)}
    raw = {'before': raw_graph(0), 'after': raw_graph(7),
           'outcome': {'kind': 'return', 'value': raw_graph(7, result)}}
    typed = {'case_id': case['case'], 'function_id': 'target.workload', 'observation_schema_version': 1,
             'fixture_sha256': contract['fixture_sha256'], 'fixture': {'status': 'ready'}, 'gaps': [],
             'before': typed_graph(0), 'after': typed_graph(7),
             'outcome': {'kind': 'return', 'graph': typed_graph(7, result)}}
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        for repeat, attempt in enumerate(bundle[lane]):
            folder = path.parent / case['case'] / (lane + '-' + str(repeat))
            assert python_provider.same(generation.read(folder / 'observation'), raw), str(folder)
            assert python_provider.same(attempt['observation'], typed), str(folder)
            execution = attempt['execution']
            assert execution['capture_complete'] is True and execution['termination'] == {'kind': 'exit', 'code': 0}
            assert execution['channels'] == {'stdout': [], 'stderr': []}
            if lane == 'baseline':
                assert execution['witness'] is None
            else:
                witness = execution['witness']
                assert witness['functions'] == {'target.workload': 1} and witness['spans'] == 1
                assert witness['pending'] == 0 and not any(witness['losses'].values())
    return 4


def recheck(folder: Path, cli: Path, provider: Path, catalogue: dict) -> dict:
    """Recompute native input bindings, health, telemetry and every typed comparison."""
    assert generation.read(folder / 'provider-inputs.json') == catalogue
    interpreter = origins.interpreter_probe()
    identities, bindings = [], {}
    for mode in MODES:
        root = folder / mode
        inputs = CacheInputs.capture(root / 'application', {'target.py': literal_source(mode).encode()})
        assert inputs.receipt() == generation.read(root / 'independent-inputs.json')
        workspace = Path((root / 'plan.stdout').read_text().strip()); inputs.verify_workspace(workspace)
        report = root / 'comparison/report.json'; assert check_report(report, mode) == 4
        data = generation.read(report); assert data['workspace'] == str(workspace)
        entry, = [e for e in data['inventory'] if e['status'] == 'ready']
        case = data['cases'][0]
        bundle = report.parent / case['case'] / 'typed-bundle.json'
        result = json.loads(command([cli, 'compare-observations', bundle], root, 'retained-comparison'))
        assert result['verdict'] == 'equivalent'
        expected = 'source-compiler' if mode in FALLBACK else 'cache-read'
        bindings[mode] = expected
        for lane in ('baseline', 'instrumented_on'):
            for repeat in range(2):
                attempt = report.parent / case['case'] / (lane + '-' + str(repeat))
                origins_data = generation.read(attempt / 'python-verified-origins.json')
                assert origins_data['source_origin'] == 'selected-input-bound'
                assert len(origins_data['selected']) == 1
                assert all(m['input_binding'] == expected for m in origins_data['selected'][0]['matches'])
                identities.append(origins.recheck_attempt(attempt, entry, provider, catalogue, interpreter,
                    selection_builder=inputs.scalar_selection, cache_builder=inputs.frozen_caches))
        inputs.verify_originals()
    assert len(identities) == len({row['application_pid'] for row in identities}) == 32
    assert len({row['sdk_pid'] for row in identities if not row['plain']}) == 16
    assert python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()}) == catalogue
    return {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
            'actual_application_launches': 32, 'sdk_processes': 16, 'complete_raw_and_typed_observations': 32,
            'reports': 8, 'recomputed_comparisons': 8, 'bindings': bindings,
            'cli_sha256': generation.capture.file_digest(cli),
            'scope': 'Ordinary timestamp/checked/unchecked caches, missing/stale/invalid-magic source fallback and '
                     'accepted older unchecked code. Receiver/effect/retained/promoted workflows, broader loaders, '
                     'shipping artefacts and full-project completion require separate qualification.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--recheck', action='store_true')
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('qualification requires assertions; disable Python optimisation')
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if any(folder.is_relative_to(root) for root in (provider, ROOT)):
        parser.error('qualification output must be external to the application and SDK')
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE='1')
    catalogue = python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()})
    if not args.recheck:
        folder.mkdir(mode=0o700)
        generation.write(folder / 'provider-inputs.json', catalogue)
        for mode in MODES:
            root = folder / mode
            workspace, inputs = prepare(root, mode, cli, provider)
            command([cli, 'run', '--workspace', workspace, '--report-dir', root / 'comparison'], root, 'run')
            check_report(root / 'comparison/report.json', mode); inputs.verify_originals()
    result = recheck(folder, cli, provider, catalogue)
    generation.write(folder / ('retained-audit.json' if args.recheck else 'qualification.json'), result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
