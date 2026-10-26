"""Check the frozen local forwarding helper without any SDK/compiler build."""

import ast
import copy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
DAY = BASE / '2026-10-26'
SOURCE = BASE / 'work/oteleq-capture-forward-framing'
OUT = DAY / 'capture-forward-components-03'
TESTS = ('test_capture_forward', 'test_capture_chunked', 'test_capture_observer.ReceiverTests')


def default_capture_proof() -> dict:
    """Keep all old framing/module code and the exact default acknowledgement."""
    old = ast.parse(subprocess.check_output(['git', 'show',
        '265f6b6:examples/otelc_capture.py'], cwd=SOURCE, text=True))
    new = ast.parse((SOURCE / 'examples/otelc_capture.py').read_text())
    shape = lambda value: ast.dump(value, include_attributes=False)
    old_receiver = next(n for n in old.body if isinstance(n, ast.ClassDef) and n.name == 'Receiver')
    new_receiver = next(n for n in new.body if isinstance(n, ast.ClassDef) and n.name == 'Receiver')
    methods_old = {n.name: n for n in old_receiver.body if isinstance(n, ast.FunctionDef)}
    methods_new = {n.name: n for n in new_receiver.body if isinstance(n, ast.FunctionDef)}
    assert set(methods_new) == set(methods_old) | {'record_body', 'received_body'}
    for name in set(methods_old) - {'do_POST'}:
        assert shape(methods_old[name]) == shape(methods_new[name]), name
    old_post, new_post = methods_old['do_POST'], methods_new['do_POST']
    start = next(i for i, n in enumerate(old_post.body)
                 if ast.unparse(n).startswith('self.server.bodies.append'))
    assert [shape(n) for n in old_post.body[:start]] == [shape(n) for n in new_post.body[:-1]]
    assert ast.unparse(new_post.body[-1]) == 'self.received_body(bytes(body))'
    received = methods_new['received_body'].body[1:]
    assert ast.unparse(received[0]) == 'self.record_body(body)'
    assert [shape(n) for n in received[1:]] == [shape(n) for n in old_post.body[start + 3:]]
    recorded = copy.deepcopy(methods_new['record_body'].body[1:])
    class BytesArgument(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.parse('bytes(body)', mode='eval').body if node.id == 'body' else node
    recorded = [BytesArgument().visit(n) for n in recorded]
    assert ast.unparse(recorded[1].value) == 'len(bytes(body))'
    # Fixed-length reads cannot exceed size; chunked reads set size=len(body).
    # Both original error paths return before the hook. Real socket regressions
    # below exercise empty/binary/chunked, truncation, deadlines and quotas.
    recorded[1].value = ast.Name(id='size', ctx=ast.Load())
    assert [shape(n) for n in recorded] == [shape(n) for n in old_post.body[start:start + 3]]
    new.body[new.body.index(new_receiver)] = old_receiver
    assert shape(new) == shape(old), 'another default capture implementation changed'
    return {'all_old_framing_and_other_module_code_ast_identical': True,
            'default_acknowledgement_ast_identical': True,
            'body_size_invariant': 'Complete fixed/chunked parser yields len(body)==size',
            'real_default_transport_regressions': 17}


def check(version: str) -> dict:
    """Keep actual interpreter output and the new module's measured floor."""
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(SOURCE / 'tests')}
    data = OUT / f'{version}.coverage'
    argv = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--include=*/otelc_capture_forward.py', '-m', 'unittest', *TESTS, '-v']
    run = subprocess.run(argv, cwd=SOURCE, env=env, capture_output=True, text=True, timeout=60)
    (OUT / f'{version}.log').write_text(run.stdout + run.stderr)
    count = re.search(r'Ran (\d+) tests', run.stderr)
    assert run.returncode == 0 and count and int(count[1]) == 38, run.stderr[-3000:]
    report = OUT / f'{version}-coverage.json'
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}', '-o', str(report)],
                   cwd=SOURCE, env=env, capture_output=True, check=True, timeout=20)
    measured = json.loads(report.read_text())['totals']
    assert measured['percent_covered'] >= 80
    return {'python': version, 'argv': argv, 'methods': 38, 'coverage': measured}


if __name__ == '__main__':
    OUT.mkdir(exist_ok=False)
    spec = importlib.util.spec_from_file_location('guard', DAY / 'review-python-label-bound.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    manifest = json.loads((DAY / 'capture-forward-source-03/source.json').read_text())
    held = guard.check_source(manifest)
    proof = default_capture_proof()
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(check, ('312', '314')))
    commands = [
        ['make', 'capture-forward-check', 'PYTHON=' + str(BASE / '2026-10-24/python-live-metrics/env-312/bin/python')],
        ['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node', str(BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),
         'README.md', 'AGENTS.md', 'docs/capture-forward.md', 'docs/quality.md', 'docs/README.md'],
        ['git', 'diff', '--check'],
    ]
    for i, command in enumerate(commands):
        result = subprocess.run(command, cwd=SOURCE, env=os.environ | {'PYTHONDONTWRITEBYTECODE': '1'},
                                capture_output=True, text=True, timeout=60)
        (OUT / f'check-{i}.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
    assert guard.check_source(manifest) == held
    result = {'status': 'pass for frozen forwarding helper and default capture preservation',
              'head': manifest['head'], 'source_preservation': held, 'checks': checks,
              'commands': commands, 'default_capture_proof': proof,
              'sdk_builds': 0, 'compiler_builds': 0, 'target_application_launches': 0,
              'scope': 'Controlled loopback Python HTTP fixtures and literal/private file tests only. No genuine Collector/SDK/Prometheus/Grafana, benchmark, provider/language or shipping admission.'}
    (OUT / 'checks.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'head': manifest['head'], 'methods_each_python': 38,
                      'source_files': held['files'], 'status': result['status']}))
