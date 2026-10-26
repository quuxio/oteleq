"""Run actual public Python live-control planning, generation and paired execution."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
RUN = ROOT / 'smoke-04'
CLI = ROOT / 'smoke-cli-01/quux-oteleq'
PROVIDER = ROOT / 'provider-ce4-312'
SOURCE = '''created=0
global_total=0
class Counter:
 total=0
 def __init__(self,start:int):
  global created
  created+=1
  self.value=start
  self.alias=self
 def add(self,amount:int)->int:
  global global_total
  self.value+=amount
  Counter.total+=amount
  global_total+=amount
  return self.value
'''


def main() -> None:
    RUN.mkdir(mode=0o700)
    source = RUN / 'application'
    source.mkdir()
    (source / 'app.py').write_text(SOURCE)
    policy = RUN / 'equivalence.toml'
    states = [(True, True), (False, True), (True, False), (False, False), (True, True)]
    schedule = []
    for index, ((collection, emission), argument, returned) in enumerate(zip(states, [1,2,3,4,5], [11,13,16,20,25])):
        args = '"case"' if index == 0 else '[' + str(argument) + ']'
        schedule.append('{action="call",arguments=' + args + ',metrics={collection=' + str(collection).lower()
                        + ',emission=' + str(emission).lower() + '},expected_baseline={kind="return_value",value={kind="integer",type="python.int",signed=true,value="'
                        + str(returned) + '"}}}')
    policy.write_text('schema_version=1\nlanguages=["python"]\n[adapters.python]\nbackend="prepared"\n'
                      'profile="python-native-origins-v2"\n[functions]\ninclude=["app.Counter.add"]\n'
                      '[limits]\nbaseline_repeats=2\ninstrumented_repeats=2\ncase_timeout_ms=30000\n'
                      '[[fixtures]]\nfunction="app.Counter.add"\ncases=[[1]]\n'
                      'receiver={factory="Counter",arguments=[10]}\nsequence=[' + ','.join(schedule) + ']\n')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('OTEL', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
    env.update(OTELEQ_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1')
    records = []
    def command(name: str, arguments: list) -> subprocess.CompletedProcess:
        argv = list(map(str, arguments))
        (RUN / (name + '.started.json')).write_text(json.dumps({'argv': argv}) + '\n')
        result = subprocess.run(argv, env=env, capture_output=True, timeout=300)
        (RUN / (name + '.stdout')).write_bytes(result.stdout)
        (RUN / (name + '.stderr')).write_bytes(result.stderr)
        (RUN / (name + '.exit')).write_text(str(result.returncode) + '\n')
        records.append({'name': name, 'argv': argv, 'returncode': result.returncode})
        print(name, result.returncode, result.stdout.decode(errors='replace')[-1200:], result.stderr.decode(errors='replace')[-1800:], flush=True)
        return result
    result = command('plan', [CLI,'plan','--source',source,'--otelc-root',PROVIDER,'--workspace-parent',RUN,'--config',policy])
    if result.returncode:
        raise SystemExit(result.returncode)
    workspace = Path(result.stdout.decode().strip())
    result = command('generate', [CLI,'generate','--workspace',workspace])
    if not result.returncode:
        result = command('run', [CLI,'run','--workspace',workspace,'--report-dir',RUN/'comparison'])
    assert (source/'app.py').read_text() == SOURCE
    (RUN/'result.json').write_text(json.dumps({'records':records,'source_sha256':hashlib.sha256(SOURCE.encode()).hexdigest(),
                                             'source_preserved':True,'exit':result.returncode,'workspace':str(workspace)},indent=2)+'\n')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
