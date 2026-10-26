"""Independently check the frozen dependency delta and exact package guard."""
from pathlib import Path
import hashlib
import json
import os
import shlex
import subprocess
import tarfile

root = Path(__file__).resolve().parent
source = root / 'source'
index = json.loads((root / 'source-index.json').read_text())

def facts():
    result = {}
    for name, digest in index['files'].items():
        path = source / name
        info = path.stat()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
        result[name] = (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return result

before = facts()
old_archive = Path('/Users/sclarke/github/otelc-qualification/2026-10-24/go-source-adapter/source-68425c2.tar')
with tarfile.open(old_archive) as archive:
    old = {member.name: hashlib.sha256(archive.extractfile(member).read()).hexdigest()
           for member in archive.getmembers() if member.isfile()}
delta = sorted(name for name in set(old) | set(index['files']) if old.get(name) != index['files'].get(name))
assert delta == ['Makefile', 'adapters/go-http/go.sum', 'adapters/go/go.mod', 'adapters/go/go.sum', 'docs/go-sdk-controls.md'], delta

go = Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
environment.update(PATH=str(go.parent) + os.pathsep + environment.get('PATH', ''),
                   GOPATH=str(root/'go-path'), GOWORK='off', GOTOOLCHAIN='local',
                   GOMODCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build/go-module-cache',
                   GOCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-http-review-b58d798/go-cache')
argv = [str(go), 'list', '-deps', '-mod=readonly', './...']
result = subprocess.run(argv, cwd=source/'adapters/go', env=environment, capture_output=True, timeout=180)
(root/'dependencies.stdout').write_bytes(result.stdout)
(root/'dependencies.stderr').write_bytes(result.stderr)
assert result.returncode == 0, result.stderr.decode(errors='replace')
packages = result.stdout.decode().splitlines()
assert packages and len(packages) == len(set(packages))
assert not any(name == 'golang.org/x/crypto/openpgp' or name.startswith('golang.org/x/crypto/openpgp/') for name in packages)
line = next(line.strip() for line in (source/'Makefile').read_text().splitlines() if line.strip().startswith("awk '/^golang.org"))
guard = shlex.split(line.replace('$$', '$'))[:-1]
controls = []
for text, expected in [(result.stdout.decode(), 0), ('', 0), ('golang.org/x/crypto/openpgp\n', 1),
                       ('golang.org/x/crypto/openpgp/packet\n', 1), ('golang.org/x/crypto/openpgp/armor\n', 1),
                       ('golang.org/x/crypto/openpgpfoo\n', 0), ('example.org/golang.org/x/crypto/openpgp\n', 0)]:
    checked = subprocess.run(guard, input=text.encode(), capture_output=True, timeout=5)
    assert checked.returncode == expected, (text, checked.returncode, checked.stderr)
    controls.append({'input': text if len(text)<100 else '<actual production package inventory>', 'exit_code': checked.returncode})
assert facts() == before
receipt = {'head': index['head'], 'dependency_delta': delta, 'production_packages': len(packages),
           'production_openpgp_imports': 0, 'exact_makefile_guard': guard, 'guard_controls': controls,
           'source_files_bytes_and_facts_held': len(before), 'new_target_applications': 0,
           'scope': 'Actual SDK production package inventory and exact guard only; raw module advisory finding remains unsuppressed.'}
(root/'dependencies-result.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt))
