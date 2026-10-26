"""Check the frozen caller revision on both supported Python runtime families."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-5361e57'
META = json.loads(SOURCE.with_suffix('.json').read_text())
SDKS = {
    'handles': Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-runtime-review-6fb166c/source-6fb166c'),
    'legacy': Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-review-7815a84/source-7815a84'),
}
RUNTIMES = {
    '312': '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
    '314': '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python',
}
IDS = re.findall(r'^\w+ \((test_[\w.]+)\) \.\.\. ok$', (ROOT / 'focused-final-312.log').read_text(), re.M)
assert len(IDS) == len(set(IDS)) == 77
ENV = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(SOURCE / 'tests'),
       'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
       'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac',
       'PATH': '/opt/homebrew/opt/openjdk@21/bin:' + os.environ['PATH']}


def preserved():
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest
               for name, digest in META['files'].items())


rows = []
for label, python in RUNTIMES.items():
    commands = [('focused', [python, '-m', 'unittest', *IDS, '-v'])]
    for profile, sdk in SDKS.items():
        script = 'qualify_java_handle_bindings.py' if profile == 'handles' else 'qualify_java_action_bindings.py'
        commands.append((profile, [python, str(SOURCE / 'tests' / script), '--otelc-root', str(sdk),
                                   '--report-dir', str(ROOT / (profile + '-' + label + '-5361e57'))]))
    for kind, command in commands:
        log = ROOT / (kind + '-' + label + '-5361e57.log')
        with log.open('wb') as stream:
            result = subprocess.run(command, cwd=SOURCE, env=ENV, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        preserved()
        row = {'runtime': label, 'kind': kind, 'exit_code': result.returncode,
               'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(), 'command': command}
        if result.returncode:
            raise AssertionError(str(log))
        if kind != 'focused':
            record = json.loads((ROOT / (kind + '-' + label + '-5361e57') / 'qualification.json').read_text())
            assert record['application_started'] is False and record['sources_preserved'] is True
            assert len(record['cases']) == (15 if kind == 'handles' else 3)
            if kind == 'handles':
                assert sum(case['accepted'] for case in record['cases']) == 12
            row['cases'] = len(record['cases'])
        rows.append(row)
        (ROOT / 'qualification-5361e57.json').write_text(json.dumps({
            'head': META['head'], 'source_files': len(META['files']), 'source_preserved': True,
            'runs': rows}, indent=2) + '\n')
        print(json.dumps({key: row[key] for key in ('runtime', 'kind', 'exit_code')}), flush=True)
