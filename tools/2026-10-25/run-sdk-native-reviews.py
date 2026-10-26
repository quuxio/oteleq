"""Run independent native component checks without changing frozen producer inputs."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path(__file__).resolve().parent
PRODUCER = Path('/Users/sclarke/github/otelc-qualification')
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
RUNNER = '''import json,sys,unittest
suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
selected=suite.countTestCases()
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps(dict(selected=selected,tests=result.testsRun,skipped=len(result.skipped),failures=len(result.failures),errors=len(result.errors))))
raise SystemExit(0 if result.wasSuccessful() and not result.skipped and result.testsRun==selected and selected else 1)
'''


def facts(path):
    info = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), info.st_dev, info.st_ino,
            info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


jobs = [
    ('ecb3c3c', BASE / 'sdk-native-review-ecb3c3c/source',
     ['test_native_launch', 'test_native_launch_tooling', 'test_native_object_launch_runtime'],
     PRODUCER / 'work/native-lifetime-launch/build/object-launch-sdk'),
    ('5f7860e', BASE / 'sdk-native-review-5f7860e/source', ['test_native_lifetimes'], None),
    ('7f82c09', BASE / 'sdk-native-review-7f82c09/source', ['test_native_lifetimes'], None),
    ('b4fa132', PRODUCER / 'work/native-lifetime-public', ['test_native_public_lifetimes'],
     PRODUCER / 'work/native-lifetime-public/build/public-object-sdk'),
]
for short, source, modules, sdk in jobs:
    root = BASE / ('sdk-native-review-' + short)
    root.mkdir(exist_ok=True)
    index_path = root / 'source-index.json'
    if short == 'b4fa132':
        index_path = PRODUCER / '2026-10-25/native-public-lifetimes/source-b4fa132.json'
    index = json.loads(index_path.read_bytes())
    before = {name: facts(source / name) for name in index['files']}
    assert all(before[name][0] == expected for name, expected in index['files'].items())
    held = {}
    if sdk:
        record = sdk / 'native-sdk-build.json'
        value = json.loads(record.read_bytes())
        for row in [*value['sources'], value['library']]:
            path = Path(row['path'])
            held[str(path)] = facts(path)
            assert held[str(path)][0] == row['sha256']
        held[str(record)] = facts(record)
    (source / 'build').mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
    env.update(PYTHONPATH=os.pathsep.join(map(str, (source, source / 'tests'))),
               PYTHONDONTWRITEBYTECODE='1', OTELC_PYTHON=str(PYTHON),
               LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config',
               OTELC_LLVM_BIN='/opt/homebrew/opt/llvm@22/bin', OTELC_CPP_ANALYSIS='1',
               LLVM_PROFILE_FILE=str(root / 'sdk-%p.profraw'),
               PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:/usr/bin:/bin')
    if sdk:
        env.update(OTELC_NATIVE_LIBRARY=str(sdk / 'libotelc_native_runtime.dylib'),
                   OTELC_PUBLIC_OBJECT_SDK=str(sdk))
    command = [str(PYTHON), '-B', '-c', RUNNER, *modules]
    state = dict(head=index['head'], status='running', source=str(source), source_files=len(before),
                 command=command, started=datetime.now(timezone.utc).isoformat())
    (root / 'inputs-before.json').write_text(json.dumps(dict(source=before,sdk=held),indent=2)+'\n')
    (root / 'status.json').write_text(json.dumps(state,indent=2)+'\n')
    started = time.monotonic()
    with (root / 'stdout').open('xb') as stdout, (root / 'stderr').open('xb') as stderr:
        result = subprocess.run(command,cwd=source,env=env,stdout=stdout,stderr=stderr,timeout=900)
    after = {name: facts(source / name) for name in index['files']}
    sdk_after = {name: facts(Path(name)) for name in held}
    state.update(status='passed' if result.returncode == 0 and before == after and held == sdk_after else 'failed',
                 exit_code=result.returncode, seconds=round(time.monotonic()-started,3),
                 source_bytes_and_facts_held=before==after, sdk_bytes_and_facts_held=held==sdk_after,
                 summary=(root / 'stdout').read_text().splitlines()[-1:],
                 finished=datetime.now(timezone.utc).isoformat())
    (root / 'inputs-after.json').write_text(json.dumps(dict(source=after,sdk=sdk_after),indent=2)+'\n')
    (root / 'status.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)
