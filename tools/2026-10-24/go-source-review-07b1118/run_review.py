"""Run independent Go foundation checks while holding all frozen sources."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
INDEX = json.loads((ROOT / 'source-index.json').read_text())
GO = '/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'

def hold() -> list[str]:
    """Return every changed frozen input."""
    return [name for name, digest in INDEX['files'].items()
            if not (SOURCE / name).is_file()
            or hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != digest]

def main() -> None:
    """Keep logs and terminal results outside the reviewed source set."""
    component = sys.argv[1]
    assert component in ('python-context', 'go-components')
    assert not hold()
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('OTEL', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
    environment.update(OTELC_GO=GO, GO=GO, GOTOOLCHAIN='local',
                       GOROOT=str(Path(GO).parent.parent),
                       PATH=str(Path(GO).parent) + os.pathsep + environment.get('PATH', ''),
                       GOPATH=str(ROOT / (component + '-go-path')),
                       GOMODCACHE=str(ROOT / (component + '-module-cache')),
                       GOCACHE=str(ROOT / (component + '-build-cache')),
                       GOWORK='off', GOFLAGS='', CGO_ENABLED='1',
                       PYTHONDONTWRITEBYTECODE='1',
                       PYTHONPATH=str(SOURCE) + os.pathsep + str(SOURCE / 'tests'))
    if component == 'python-context':
        commands = [[sys.executable, '-m', 'unittest', '-v', 'test_go_context_bundle',
                     'test_go_upstream_builder', 'test_go_context_integration']]
        directory = SOURCE
    else:
        commands = [[GO, 'vet', '-mod=readonly', './...'],
                    [GO, 'test', '-mod=readonly', '-race', '-count=1',
                     '-coverprofile=' + str(ROOT / 'go-coverage.out'), './...']]
        directory = SOURCE / 'adapters/go'
    records = []
    started = time.monotonic()
    with (ROOT / (component + '.log')).open('xb') as output:
        for argv in commands:
            began = time.monotonic()
            process = subprocess.run(argv, cwd=directory, env=environment,
                                     stdout=output, stderr=subprocess.STDOUT, timeout=2400)
            records.append({'argv': argv, 'returncode': process.returncode,
                            'seconds': round(time.monotonic() - began, 3)})
            if process.returncode:
                break
    changed = hold()
    result = {'component': component, 'head': INDEX['head'],
              'commands': records, 'seconds': round(time.monotonic() - started, 3),
              'source_files': len(INDEX['files']), 'changed': changed,
              'source_preserved': not changed,
              'at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (ROOT / (component + '-result.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    raise SystemExit(0 if not changed and all(row['returncode'] == 0 for row in records) else 1)

if __name__ == '__main__':
    main()
