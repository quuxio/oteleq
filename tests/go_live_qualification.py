"""Complete fixed-corpus graph expectations for generated and retained Go tests."""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

import go_live_fixture as fixture
import go_live_receipt as receipt
import qualify_go_receivers as receivers


def source_facts(source: Path, *, changed: bool = False) -> dict:
    """Freeze every original fixture byte and ordinary file identity."""
    literals = fixture.sources(changed=changed)
    paths = {path.relative_to(source).as_posix(): path for path in source.rglob('*') if path.is_file()}
    fixture.exact(sorted(paths), sorted(literals))
    facts = {}
    for name, raw in literals.items():
        path = paths[name]
        receipt.require(not path.is_symlink() and path.read_bytes() == raw, 'fixture source changed')
        info = path.stat()
        facts[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'device': info.st_dev,
                       'inode': info.st_ino, 'size': info.st_size, 'mode': info.st_mode,
                       'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}
    return facts


def make_source(source: Path, *, changed: bool = False) -> dict:
    for name, raw in fixture.sources(changed=changed).items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return source_facts(source, changed=changed)


def contract(value: dict, method: str, case: str) -> None:
    roots = sorted(fixture.ROOTS)
    error = {'kind': 'error', 'category': 'panic', 'type': 'go.string'}
    fixture.exact(value, {'observation_schema_version': 1, 'case_id': case,
        'function_id': fixture.runtime_function(method), 'fixture_sha256': value['fixture_sha256'],
        'required_roots': roots, 'expected_baseline': error, 'steps': [
            {'id': 'step-' + str(index), 'action': 'call', 'required_roots': roots,
             'expected_baseline': error if index == 4 else {'kind': 'return'}} for index in range(5)]})
    receipt.require(type(value['fixture_sha256']) is str and len(value['fixture_sha256']) == 64
                    and set(value['fixture_sha256']) <= set('0123456789abcdef'), 'invalid fixture digest')


def check_report(path: Path, count: int, *, start: str, provider: Path,
                 changed: bool = False, original: Path | None = None) -> int:
    """Check every value, alias, call, control and raw receipt in all four repeats."""
    report = receipt.read(path)
    if original is not None:
        receipt.identical_archive(original.parent, path.parent)
    receipt.require(report['source_preserved'] is True and report['blocked'] == []
                    and len(report['cases']) == count, 'incomplete generated report')
    fixture.exact(report['claim'], 'equivalence over these tests and observations')
    functions = {fixture.function(name): name for name in (*fixture.METHODS, 'added')}
    ready = [row['otelc_function'] for row in report['inventory'] if row['status'] == 'ready']
    all_ready = sorted(fixture.function(name) for name in
                       (*fixture.METHODS, 'added') if name != 'added' or changed)
    receipt.require(sorted(ready) in (all_ready, [fixture.function('transient')]), 'unexpected ready inventory')
    selected = [case['function'] for case in report['cases']]
    receipt.require(len(set(selected)) == count and set(selected) <= set(ready), 'repeated or foreign cases')
    if count > 1:
        fixture.exact(sorted(selected), sorted(ready))
    observed = 0
    for case in report['cases']:
        method = functions[case['function']]
        fixture.exact(case['exit_code'], int(method == 'transient'))
        fixture.exact(case['receiver_fixture']['arguments'], [10])
        fixture.exact(case['arguments_requested'], case['arguments'])
        amount, = case['arguments']
        receipt.require(type(amount) is int and amount in (0, 7), 'unexpected case argument')
        folder = path.parent / case['case']
        bundle = receipt.read(folder / 'typed-bundle.json')
        fixture.exact(bundle['typed_schema_version'], 1)
        receipt.require(len(bundle['cases']) == 1, 'unexpected typed case denominator')
        typed, = bundle['cases']
        contract(typed['contract'], method, case['case'])
        expected_functions = {fixture.runtime_function(method): 5, receipt.FACTORY: 1}
        fixture.exact(typed['expected_functions'], expected_functions)
        fixture.exact(typed['expected_spans'], 6)
        for lane in ('baseline', 'instrumented_on'):
            receipt.require(len(typed[lane]) == 2, 'missing case repeat')
            for repeat, attempt in enumerate(typed[lane]):
                target = folder / (lane + '-' + str(repeat))
                observed += 1
                expected = fixture.observation(method, amount, lane != 'baseline', case['case'],
                    typed['contract']['fixture_sha256'], changed=changed)
                fixture.exact(attempt['observation'], expected)
                fixture.exact(receipt.read(target / 'typed-observation.json'), expected)
                execution = attempt['execution']
                fixture.exact(execution, {'capture_complete': True, 'channels': {'stdout': [], 'stderr': []},
                    'source_sha256_before': report['source_sha256'], 'source_sha256_after': report['source_sha256'],
                    'termination': {'kind': 'exit', 'code': 0}, 'witness': execution['witness']})
                fixture.exact([row['metrics'] for row in case['sequence']], list(fixture.states(start)))
                # copytree archives preserve bytes, not original inode/link
                # identity. Only an independently bound original can supply
                # physical publisher facts; every archived byte matched above.
                evidence = original.parent / case['case'] / (lane + '-' + str(repeat)) if original else target
                receipt.check(evidence, method, start, lane == 'baseline', execution['witness'], provider)
                receivers.scope_attempt(evidence, ())
    fixture.exact(report['exit_code'], int('transient' in (functions[name] for name in selected)))
    return observed
