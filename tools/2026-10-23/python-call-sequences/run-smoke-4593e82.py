"""Run four real legacy-provider applications with 32 declared Python calls."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parent
SOURCE = ROOT / 'source-4593e82'
CLI = ROOT / 'quux-oteleq-4593e82'
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/manifest.json')
PROVIDER = MANIFEST.parent / 'provider'
FOLDER = ROOT / 'smoke-4593e82'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    counts = {}
    for group in ('source_sha256', 'products_sha256', 'dependencies'):
        for name, expected in manifest[group].items():
            path = PROVIDER / name
            if isinstance(expected, str):
                assert digest(path) == expected, name
            elif 'sha256' in expected:
                assert digest(path) == expected['sha256'], name
            else:
                assert path.is_symlink() and os.readlink(path) == expected['symlink'], name
                assert str(path.resolve()) == expected['resolved'], name
        counts[group] = len(manifest[group])
    python = manifest['tools']['python']
    assert digest(Path(python['resolved'])) == python['sha256']
    assert digest(Path(sys.executable).resolve()) == python['sha256']
    seal = json.loads((ROOT / 'source-4593e82.json').read_text())
    assert all(digest(SOURCE / name) == expected for name, expected in seal['files'].items())
    return {'provider_commit': manifest['source_commit'], 'provider_counts': counts,
            'provider_manifest_sha256': digest(MANIFEST), 'selected_tool_roles': 1,
            'python_sha256': python['sha256'], 'consumer_commit': seal['commit'],
            'consumer_files': len(seal['files']), 'cli_sha256': digest(CLI)}


def command(name: str, arguments: list[str], environment: dict) -> None:
    argv = [str(CLI), *arguments]
    result = subprocess.run(argv, cwd=FOLDER, env=environment,
                            capture_output=True, timeout=180, check=False)
    (FOLDER / (name + '.stdout')).write_bytes(result.stdout)
    (FOLDER / (name + '.stderr')).write_bytes(result.stderr)
    (FOLDER / (name + '.exit')).write_text(str(result.returncode) + '\n')
    (FOLDER / (name + '.argv.json')).write_text(json.dumps(argv) + '\n')
    assert result.returncode == 0, (name, result.returncode, result.stderr.decode(errors='replace'))


def integer(value: int) -> dict:
    return {'type': 'int', 'value': str(value)}


def graph(argument: int, calls: int, *, outcome: bool = False) -> dict:
    """A literal oracle independent of application code and the producer encoder."""
    roots = {'arguments': {'ref': 0}, 'receiver': {'ref': 1},
             'static:Counter.total': integer(7 if calls else 0)}
    if outcome:
        roots['result'] = integer(17)
    return {'roots': roots, 'nodes': [
        {'type': 'builtins.list', 'items': [integer(argument)]},
        {'type': '_oteleq_target.Counter', 'fields': [
            ['value', integer(17 if calls else 10)],
            ['alias', {'ref': 1}], ['calls', integer(calls)]]}]}


def expected_observation() -> dict:
    steps = []
    for index in range(32):
        argument = 7 if index == 0 else 0
        steps.append({'id': 'step-' + str(index), 'action': 'call', 'gaps': [],
                      'before': graph(argument, index),
                      'outcome': {'kind': 'return', 'value': graph(argument, index + 1, outcome=True)},
                      'after': graph(argument, index + 1)})
    return {'before': steps[0]['before'], 'outcome': steps[-1]['outcome'],
            'after': steps[-1]['after'], 'steps': steps}


def main() -> None:
    assert not FOLDER.exists()
    FOLDER.mkdir()
    record = {'started_at': datetime.datetime.now(datetime.UTC).isoformat(), 'before': verify()}
    receipt = ROOT / 'smoke-run-4593e82.json'
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    app = FOLDER / 'application'
    app.mkdir()
    original = '''class Counter:
 total=0
 def __init__(self,start:int):
  self.value=start
  self.alias=self
  self.calls=0
 def add(self,amount:int)->int:
  self.value+=amount
  self.calls+=1
  Counter.total+=amount
  return self.value
'''
    (app / 'app.py').write_text(original)
    parent = FOLDER / 'workspaces'
    parent.mkdir()
    expectation = '{kind="return_value",value={kind="integer",type="python.int",value="17",signed=true}}'
    calls = ['{action="call",arguments="case",expected_baseline=' + expectation + '}']
    calls.extend('{action="call",arguments=[0],expected_baseline=' + expectation + '}' for _ in range(31))
    policy = FOLDER / 'equivalence.toml'
    policy.write_text('schema_version=1\nlanguages=["python"]\n[functions]\ninclude=["app.Counter.add"]\n'
                      '[[fixtures]]\nfunction="app.Counter.add"\ncases=[[7]]\n'
                      'receiver={factory="Counter",arguments=[10]}\nsequence=[' + ',\n'.join(calls) + ']\n')
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                       OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(CLI))
    environment.pop('OTELC_CONFIG', None)
    try:
        command('plan', ['plan', '--source', str(app), '--otelc-root', str(PROVIDER),
                         '--config', str(policy), '--workspace-parent', str(parent)], environment)
        workspaces = list(parent.glob('oteleq-run-*'))
        assert len(workspaces) == 1
        workspace = workspaces[0]
        command('generate', ['generate', '--workspace', str(workspace)], environment)
        command('run', ['run', '--workspace', str(workspace),
                        '--report-dir', str(FOLDER / 'comparison')], environment)
        report = json.loads((FOLDER / 'comparison/report.json').read_text())
        assert report['source_preserved'] and not report['blocked'] and len(report['cases']) == 1
        assert report['cases'][0]['exit_code'] == 0
        commands = [path for path in (FOLDER / 'comparison').rglob('command.json')
                    if path.parent.name.startswith(('baseline-', 'instrumented_on-'))]
        assert len(commands) == 4
        expected = expected_observation()
        for path in commands:
            assert json.loads((path.parent / 'observation').read_text()) == expected, str(path)
            assert (path.parent / 'typed-observation.json').is_file()
        assert (app / 'app.py').read_text() == original
        record.update(exit_code=0, actual_application_launches=4, calls_per_application=32,
                      independently_expected_raw_observations=4,
                      telemetry='CLI validates32 complete serial selected roots, metrics, zero losses and final drain; independent retained decode remains pending.')
    except Exception as error:
        record.update(exit_code=1, error=repr(error))
        raise
    finally:
        record.update(after=verify(), finished_at=datetime.datetime.now(datetime.UTC).isoformat())
        assert record['before'] == record['after']
        receipt.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record))


if __name__ == '__main__':
    main()
