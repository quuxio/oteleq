"""Review-only native HTTP regression using an external overlay and private modfile."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
GO = '/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
HTTP = Path('/Users/sclarke/github/otelc-qualification/2026-10-24/go-source-adapter/http-retained-acceptance/execution/build/private/.otelc-http/otelhttp')
index = json.loads((ROOT / 'source-index.json').read_text())
before = {name: ((SOURCE / name).stat(), hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()) for name in index['files']}
assert all(value[1] == index['files'][name] for name, value in before.items())
output = ROOT / 'context-reuse-02'
output.mkdir(mode=0o700)
modfile = output / 'go.mod'
modfile.write_bytes((SOURCE / 'adapters/go-http/go.mod').read_bytes())
(output / 'go.sum').write_bytes((SOURCE / 'adapters/go-http/go.sum').read_bytes())
overlay = output / 'overlay.json'
overlay.write_text(json.dumps({'Replace': {str(SOURCE / 'adapters/go-http/zz_context_reuse_test.go'): str(ROOT / 'context_reuse_test.go')}}) + '\n')
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
environment.update(GOCACHE=str(ROOT / 'go-cache'),
    GOMODCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build/go-module-cache',
    GOTOOLCHAIN='local', GOPROXY='https://proxy.golang.org', GOSUMDB='sum.golang.org', GOWORK='off', GOFLAGS='',
    PATH=str(Path(GO).parent) + ':/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')
commands = [[GO, 'mod', 'edit', '-modfile=' + str(modfile), '-replace=io.quux.otelc/go=' + str(SOURCE / 'adapters/go'),
             '-replace=go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp=' + str(HTTP)],
            [GO, 'mod', 'tidy', '-modfile=' + str(modfile)],
            [GO, 'test', '-mod=readonly', '-modfile=' + str(modfile), '-overlay=' + str(overlay),
             '-count=1', '-run', '^TestReturnedRequestContextDoesNotSuppressTheNextClientOperation$', '-v', './...']]
receipts = []
for number, command in enumerate(commands):
    started = time.monotonic()
    with (output / f'{number}.stdout').open('xb') as stdout, (output / f'{number}.stderr').open('xb') as stderr:
        process = subprocess.run(command, cwd=SOURCE / 'adapters/go-http', env=environment,
                                 stdout=stdout, stderr=stderr, timeout=300)
    receipts.append({'argv': command, 'exit_code': process.returncode, 'seconds': round(time.monotonic() - started, 3)})
    (output / 'commands.json').write_text(json.dumps(receipts, indent=2) + '\n')
    if process.returncode and number < 2:
        raise SystemExit('prerequisite failed; inspect retained command channels')
def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
held = all(signature((SOURCE / name).stat()) == signature(value[0]) and hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == value[1]
           for name, value in before.items())
result = {'head': index['head'], 'test_exit_code': receipts[-1]['exit_code'], 'source_files_held': len(before) if held else 0,
          'review_fixture_sha256': hashlib.sha256((ROOT / 'context_reuse_test.go').read_bytes()).hexdigest(),
          'source_modified': False, 'scope': 'One independent component regression; not broad Go qualification.'}
(output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
raise SystemExit(receipts[-1]['exit_code'] if held else 2)
