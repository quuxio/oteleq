"""Review the frozen benchmark correction with actual owned CPU/RSS observations."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
INDEX = json.loads((ROOT / 'source-index.json').read_text())
OUTPUT = ROOT / 'focused-review-prepared'
OUTPUT.mkdir(mode=0o700)


def facts():
    result = {}
    for name, digest in INDEX['files'].items():
        path = SOURCE / name
        info = path.stat()
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == digest
        result[name] = (actual, info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return result


before = facts()
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
environment.update(PYTHONPATH='tests:.', PYTHONDONTWRITEBYTECODE='1',
    PATH='/opt/homebrew/Cellar/node@24/24.21.0_2/bin:/opt/homebrew/opt/llvm@22/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin')
results = []
for version in ('312', '314'):
    python = ROOT.parent / 'python-live-metrics' / ('env-' + version) / 'bin/python'
    coverage = OUTPUT / (version + '.coverage')
    argv = [str(python), '-B', '-m', 'coverage', 'run', '--data-file=' + str(coverage),
            '--source=otelc.benchmark_process,otelc.node_benchmark,otelc.python_benchmark',
            '-m', 'unittest', '-v', 'test_benchmark_finalization', 'test_node_benchmark', 'test_python_benchmark']
    (OUTPUT / (version + '-command.json')).write_text(json.dumps({'argv': argv, 'cwd': str(SOURCE), 'head': INDEX['head']}, indent=2) + '\n')
    started = time.monotonic()
    with (OUTPUT / (version + '.log')).open('xb') as log:
        process = subprocess.run(argv, cwd=SOURCE, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=600)
    held = facts() == before
    result = {'python': version, 'exit_code': process.returncode, 'seconds': round(time.monotonic() - started, 3),
              'source_files_held': len(before) if held else 0}
    if process.returncode == 0:
        destination = OUTPUT / (version + '-coverage.json')
        subprocess.run([str(python), '-B', '-m', 'coverage', 'json', '--data-file=' + str(coverage), '-o', str(destination)],
                       cwd=SOURCE, env=environment, capture_output=True, check=True)
        data = json.loads(destination.read_text())
        result['line_percent'] = {Path(name).name: value['summary']['percent_covered'] for name, value in data['files'].items()}
    (OUTPUT / (version + '-result.json')).write_text(json.dumps(result, indent=2) + '\n')
    results.append(result)
    print(json.dumps(result), flush=True)
    if process.returncode or not held:
        raise SystemExit(1)
(OUTPUT / 'result.json').write_text(json.dumps({'head': INDEX['head'], 'results': results,
    'scope': 'Actual component regression and source preservation. Includes the explicit typed-identity correction; no performance estimate on this busy host.'}, indent=2) + '\n')
