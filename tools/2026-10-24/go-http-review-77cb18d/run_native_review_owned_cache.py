"""Independently rebuild pinned official HTTP source and test the marker correction."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
GO = '/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
MODULE = 'go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp'
VERSION = 'v0.72.0'
INDEX = json.loads((ROOT / 'source-index.json').read_text())
OUTPUT = ROOT / 'native-review-owned-cache'
OUTPUT.mkdir(mode=0o700)


def facts():
    values = {}
    for name, digest in INDEX['files'].items():
        path = SOURCE / name
        info = path.stat()
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == digest
        values[name] = (actual, info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return values


before = facts()
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
environment.update(GOCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-http-review-b58d798/go-cache',
    GOMODCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build/go-module-cache',
    GOPATH=str(ROOT / 'go-path'), GOTOOLCHAIN='local', GOWORK='off', GOFLAGS='', GOPROXY='https://proxy.golang.org', GOSUMDB='sum.golang.org',
    PATH=str(Path(GO).parent) + ':/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')
receipts = []


def command(argv, cwd):
    number = len(receipts)
    started = time.monotonic()
    with (OUTPUT / f'{number}.stdout').open('xb') as stdout, (OUTPUT / f'{number}.stderr').open('xb') as stderr:
        process = subprocess.run(argv, cwd=cwd, env=environment, stdout=stdout, stderr=stderr, timeout=300)
    receipts.append({'argv': argv, 'cwd': str(cwd), 'exit_code': process.returncode, 'seconds': round(time.monotonic() - started, 3)})
    (OUTPUT / 'commands.json').write_text(json.dumps(receipts, indent=2) + '\n')
    assert process.returncode == 0, (OUTPUT / f'{number}.stderr').read_text()[-1500:]
    return (OUTPUT / f'{number}.stdout').read_bytes()


identity = json.loads(command([GO, 'mod', 'download', '-json', MODULE + '@' + VERSION], OUTPUT))
assert identity['Path'] == MODULE and identity['Version'] == VERSION
assert identity['Sum'] == 'h1:LxwW/9ctSCv+QkE/cLR7M91ZIkXNMqJtEMi1vCw9U8s='
assert identity['GoModSum'] == 'h1:tOsftB4SslBwwErVEPaenU2RpThXWPIU8DoJHEC4dyw='
archive = Path(identity['Zip'])
assert archive.stat().st_size <= 16 * 1024 * 1024
assert hashlib.sha256(archive.read_bytes()).hexdigest() == 'e9e9f34bc563d5114bc6c2760cf2b3d15ae82b0bbd635cd534ae3ccce2ac3300'
upstream = OUTPUT / 'official-http'
upstream.mkdir()
files = {}
with zipfile.ZipFile(archive) as zipped:
    for member in zipped.infolist():
        prefix = MODULE + '@' + VERSION + '/'
        assert member.filename.startswith(prefix)
        name = member.filename[len(prefix):]
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        if name in ('LICENSE', 'go.mod', 'go.sum') or name.endswith('.go') and not name.endswith('_test.go'):
            assert name not in files and member.file_size <= 16 * 1024 * 1024
            files[name] = zipped.read(member)
assert sum(map(len, files.values())) <= 16 * 1024 * 1024
needle = b'SetStatus(codes.Error, err.Error())'
assert files['transport.go'].count(needle) == 3
files['transport.go'] = files['transport.go'].replace(needle, b'SetStatus(codes.Error, "")')
for name, raw in files.items():
    path = upstream / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
modfile = OUTPUT / 'go.mod'
modfile.write_bytes((SOURCE / 'adapters/go-http/go.mod').read_bytes())
(OUTPUT / 'go.sum').write_bytes((SOURCE / 'adapters/go-http/go.sum').read_bytes())
package = SOURCE / 'adapters/go-http'
assert not command([str(Path(GO).parent / 'gofmt'), '-l', *map(str, package.glob('*.go'))], package).strip()
command([GO, 'mod', 'edit', '-modfile=' + str(modfile), '-replace=io.quux.otelc/go=' + str(SOURCE / 'adapters/go'),
         '-replace=' + MODULE + '=' + str(upstream)], package)
command([GO, 'mod', 'tidy', '-modfile=' + str(modfile)], package)
command([GO, 'vet', '-mod=readonly', '-modfile=' + str(modfile), './...'], package)
command([GO, 'test', '-mod=readonly', '-modfile=' + str(modfile), '-race', '-count=1',
         '-coverprofile=' + str(OUTPUT / 'coverage.out'), '-v', './...'], package)
totals, hits = {}, {}
for line in (OUTPUT / 'coverage.out').read_text().splitlines()[1:]:
    position, size, count = line.split()
    name = position.split(':', 1)[0]
    totals[name] = totals.get(name, 0) + int(size)
    hits[name] = hits.get(name, 0) + (int(size) if int(count) else 0)
percentages = {name: 100 * hits[name] / size for name, size in totals.items()}
assert {Path(name).name for name in percentages} == {'dispatch.go', 'http.go'}
assert all(value >= 80 for value in percentages.values())
assert facts() == before
result = {'head': INDEX['head'], 'result': 'passed', 'source_files_held': len(before), 'statement_percent': percentages,
    'official_archive_sha256': 'e9e9f34bc563d5114bc6c2760cf2b3d15ae82b0bbd635cd534ae3ccce2ac3300',
    'official_production_files': len(files), 'exact_original_regression': 'TestReturnedRequestContextDoesNotSuppressTheNextClientOperation',
    'scope': 'Independent pinned-module reconstruction, format/vet/race/component checks and returned-context regression; public native workflow and complete Go admission remain separate.'}
(OUTPUT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
