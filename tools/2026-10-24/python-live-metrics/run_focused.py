"""Hold all current sources during focused coverage/regression checks."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-live-metrics')

def main() -> None:
    label = sys.argv[1]
    index = json.loads((ROOT / 'source-strict-error.json').read_text())
    assert all(hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() == digest for name,digest in index['files'].items())
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
               OTELC_NODE='/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',
               PYTHONPATH=str(SOURCE/'adapters/generation')+os.pathsep+str(SOURCE/'examples')+os.pathsep+str(SOURCE/'tests'))
    if label == 'retained':
        argv = [sys.executable,'-m','coverage','run','--data-file='+str(ROOT/'retained-host-strict.coverage'),
                '--include=*/adapters/generation/live_control.py,*/adapters/generation/python_control*.py,*/adapters/generation/python_live.py,*/adapters/generation/python_telemetry.py',
                str(ROOT/'audit_smoke04_v3.py')]
    else:
        argv = [sys.executable,'-m','coverage','run','--data-file='+str(ROOT/('unit-'+label+'.coverage')),
                '--include=*/adapters/generation/live_control.py,*/adapters/generation/python_control*.py,*/adapters/generation/python_checkpoint.py,*/adapters/generation/python_live.py,*/adapters/generation/python_telemetry.py',
                '-m','unittest','-v','test_generation_python_live','test_generation_python_control',
                'test_generation_python_controlled_telemetry','test_generation_python_telemetry',
                'test_generation_python_launch','test_generation_python_cache','test_generation_python_health',
                'test_generation_node_control','test_generation_node_control_receipt','test_generation_node_live']
    with (ROOT/('focused-'+label+'.log')).open('xb') as output:
        result = subprocess.run(argv,cwd=SOURCE,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=300)
    changed = [name for name,digest in index['files'].items() if hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() != digest]
    receipt = {'label':label,'returncode':result.returncode,'source_files':len(index['files']),'changed':changed,'source_preserved':not changed}
    (ROOT/('focused-'+label+'-result.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
    raise SystemExit(0 if result.returncode == 0 and not changed else 1)

if __name__ == '__main__':
    main()
