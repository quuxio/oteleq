"""Independent fixed command receipts and adversarial checks for sequence qualifiers."""
import json
from pathlib import Path
import sys
from collections.abc import Callable
import unittest

METHODS = ('identity', 'secret', 'transient', 'fail', 'recursive', 'touch')
CONTROL_VERDICTS = {
    'missing-call': (3, 'inconclusive'), 'reordered-calls': (3, 'inconclusive'),
    'missing-field': (1, 'different_observed'), 'missing-method-witness': (3, 'inconclusive'),
    'undeclared-intermediate-error': (2, 'blocked'),
}


def write_receipts(folder: Path, function_id: Callable[[str], str], refusals: tuple[str, ...]) -> Path:
    """Construct literal expected commands without asking the verifier for its own contract."""
    cli, provider = folder / 'cli', folder / 'provider'
    workspace, reduced = folder / 'cases/workspace', folder / 'shrink/workspace'
    workspace.mkdir(parents=True)
    reduced.mkdir(parents=True)
    (folder / 'cases/plan.stdout').write_text(str(workspace))
    (workspace / 'plan.json').write_text(json.dumps({'otelc_root': str(provider)}))
    (folder / 'shrink/shrink.json').write_text(json.dumps({'workspace': str(reduced)}))
    (folder / 'comparison').mkdir()
    cases = [{'function': function_id(method), 'case': method} for method in METHODS]
    (folder / 'comparison/report.json').write_text(json.dumps({'cases': cases}))
    operations = {
        'run': (1, [cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison']),
        'framework': (1, [sys.executable, workspace / 'tests/test_equivalence.py']),
        'export': (0, [cli, 'export-tests', '--workspace', workspace, '--destination', folder / 'exported', '--apply']),
        'export-run': (1, [cli, 'run', '--workspace', folder / 'exported', '--report-dir', folder / 'export-comparison']),
        'export-framework': (1, [sys.executable, folder / 'exported/tests/test_equivalence.py']),
        'shrink': (1, [cli, 'shrink', '--workspace', workspace, '--case', 'transient', '--report-dir', folder / 'shrink', '--trials', '1']),
        'reduced-framework': (1, [sys.executable, reduced / 'tests/test_equivalence.py']),
        'reduced-replay': (1, [cli, 'replay', '--workspace', reduced, '--case', 'transient']),
        'changed-source': (4, [cli, 'replay', '--workspace', workspace, '--case', 'transient']),
    }
    for method in METHODS:
        operations['replay-' + method] = (int(method == 'transient'), [cli, 'replay', '--workspace', workspace, '--case', method])
    for name, (expected, _) in CONTROL_VERDICTS.items():
        operations[name] = (expected, [cli, 'compare-observations', folder / (name + '.json')])

    def receipt(base, name, expected, argv):
        (base / (name + '.started.json')).write_text(json.dumps({'expected_exit': expected, 'argv': list(map(str, argv))}))
        (base / (name + '.exit')).write_text(str(expected) + '\n')
        (base / (name + '.stdout')).write_text(json.dumps({'verdict': CONTROL_VERDICTS[name][1]}) if name in CONTROL_VERDICTS else '')
        (base / (name + '.stderr')).write_text('oteleq: application source or immutable snapshot changed\n' if name == 'changed-source' else '')

    for name, (expected, argv) in operations.items():
        receipt(folder, name, expected, argv)
    for name in ('cases', 'edge-one', 'edge-thirty-two', *refusals):
        route = folder / name
        route.mkdir(exist_ok=True)
        selected = route / 'workspace'
        receipt(route, 'plan', 0, [cli, 'plan', '--source', route / 'application', '--otelc-root', provider,
            '--workspace-parent', route, '--config', route / 'equivalence.toml'])
        receipt(route, 'generate', 0, [cli, 'generate', '--workspace', selected])
        if name != 'cases':
            receipt(route, 'run', 4 if name in refusals else 0,
                [cli, 'run', '--workspace', selected, '--report-dir', route / 'comparison'])
        (route / 'plan.stdout').write_text(str(selected))
    (folder / 'cases/plan.stdout').write_text(str(workspace))
    return cli


def reject_bad_receipts(test: unittest.TestCase, verify: Callable, folder: Path, cli: Path) -> None:
    """Missing terminals, wrong exits, changed argv and false verdicts must refuse."""
    for fault in ('missing', 'exit', 'argv', 'verdict'):
        path = folder / ('export-framework.exit' if fault in ('missing', 'exit') else
            'run.started.json' if fault == 'argv' else 'missing-call.stdout')
        original = path.read_bytes()
        if fault == 'missing':
            path.unlink()
        elif fault == 'exit':
            path.write_text('0\n')
        elif fault == 'argv':
            marker = json.loads(original)
            marker['argv'][1] = 'clean'
            path.write_text(json.dumps(marker))
        else:
            path.write_text('{"verdict":"equivalent_observed"}')
        with test.subTest(fault=fault), test.assertRaises((AssertionError, FileNotFoundError)):
            verify(folder, cli)
        path.write_bytes(original)
