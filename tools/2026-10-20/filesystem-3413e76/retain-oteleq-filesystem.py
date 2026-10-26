"""Retain terminal filesystem evidence, exact sources and no-follow file manifests."""
from collections import defaultdict
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys

ROOT = Path('/private/tmp/oteleq-filesystem-work')
RUNTIME = json.loads(Path('/private/tmp/oteleq-filesystem-runtime.json').read_text())
EVIDENCE = Path('/private/tmp/oteleq-filesystem-3413e76-evidence')
DESTINATION = Path('/Users/sclarke/Documents/oteleq-qualification/2026-10-20/filesystem-3413e76')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def manifest(root):
    records = {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            records[name] = {'kind': 'symlink', 'target': os.readlink(path)}
        elif stat.S_ISREG(metadata.st_mode):
            records[name] = {'kind': 'file', 'sha256': digest(path), 'bytes': metadata.st_size, 'mode': mode}
        elif stat.S_ISDIR(metadata.st_mode):
            records[name] = {'kind': 'directory', 'mode': mode}
        else:
            raise ValueError('Unexpected special file in retained corpus: ' + str(path))
    return records


def clone(source, destination):
    subprocess.run(['/bin/cp', '-cR', str(source), str(destination)], check=True)
    before, after = manifest(source), manifest(destination)
    assert before == after, source
    return before


qualification = json.loads((EVIDENCE / 'QUALIFICATION.json').read_text())
assert qualification['cli_sha256'] == RUNTIME['cli_sha256'] == digest(Path(RUNTIME['cli']))
assert digest(EVIDENCE / 'executed-resume-qualifier.py') == RUNTIME['resume_qualifier_sha256']
assert qualification['actual_application_launches'] > 288
DESTINATION.mkdir(mode=0o700)
counts = {}
for name, source in {'final': EVIDENCE,
                     'development': Path('/private/tmp/oteleq-filesystem-eight-development'),
                     'presentation': Path('/private/tmp/oteleq-filesystem-3413e76-presentation')}.items():
    records = clone(source, DESTINATION / name)
    (DESTINATION / (name + '-raw-manifest.json')).write_text(json.dumps(records, indent=2) + '\n')
    counts[name] = {'records': len(records), 'files': sum(row['kind'] == 'file' for row in records.values()),
                    'directories': sum(row['kind'] == 'directory' for row in records.values()),
                    'symlinks': sum(row['kind'] == 'symlink' for row in records.values())}
provider = Path(RUNTIME['provider'])
provider_records = clone(provider, DESTINATION / provider.name)
(DESTINATION / 'provider-raw-manifest.json').write_text(json.dumps(provider_records, indent=2) + '\n')
shutil.copy2(Path(str(provider) + '.json'), DESTINATION / (provider.name + '.json'))
for pattern in ['oteleq-filesystem*.log', 'oteleq-filesystem*sonar*.json',
                'oteleq-integrated-0419a51-provider-verification.json']:
    for source in Path('/private/tmp').glob(pattern):
        shutil.copy2(source, DESTINATION / source.name)
for source in [Path(RUNTIME['cli']), Path('/private/tmp/oteleq-filesystem-runtime.json'), Path(__file__)]:
    shutil.copy2(source, DESTINATION / source.name)
subprocess.run(['git', 'archive', '--format=tar', '--output=' + str(DESTINATION / 'runtime-source.tar'), RUNTIME['commit']], cwd=ROOT, check=True)
subprocess.run(['git', 'archive', '--format=tar', '--output=' + str(DESTINATION / 'executed-checker-source.tar'), RUNTIME['resume_qualifier_commit']], cwd=ROOT, check=True)
groups = defaultdict(list)
for command in EVIDENCE.rglob('command.json'):
    if (command.parent / 'http-capture.json').is_file():
        groups[digest(command)].append(command.parent)
copied = []
for paths in groups.values():
    for path in paths[1:]:
        assert manifest(paths[0]) == manifest(path)
        copied.append({'original': str(paths[0].relative_to(EVIDENCE)), 'copy': str(path.relative_to(EVIDENCE))})
assert len(groups) == qualification['actual_application_launches']
assert len(copied) == 32
reconciliation = {'raw_attempt_folders': sum(map(len, groups.values())), 'actual_launches': len(groups),
                  'copied_attempts': copied, 'identity': 'SHA256 of retained exact command.json; copied original-shrink attempts compared byte/mode/entry-wise'}
(DESTINATION / 'LAUNCH-RECONCILIATION.json').write_text(json.dumps(reconciliation, indent=2) + '\n')
inputs = [Path(sys.executable), Path('/opt/homebrew/opt/node@24/bin/node')]
producer = json.loads(Path(str(provider) + '.json').read_text())
assert digest(Path(str(provider) + '.json')) == RUNTIME['provider_manifest_sha256']
for field in ('source_sha256', 'products_sha256'):
    for name, expected in producer[field].items():
        assert digest(provider / name) == expected, (field, name)
for name, record in producer['dependencies'].items():
    source = provider / name
    if 'symlink' in record:
        assert source.is_symlink() and os.readlink(source) == record['symlink'], name
    else:
        assert digest(source) == record['sha256'], name
for record in producer['tools'].values():
    assert digest(Path(record['path'])) == record['sha256'], record['path']
inputs.extend(Path(record['path']) for record in producer['tools'].values())
for plan in EVIDENCE.glob('cases/*/plan.json'):
    data = json.loads(plan.read_text())
    inputs.extend(Path(path) for tools in data['tools'].values() for path in tools.values())
for package in ['google.protobuf', 'opentelemetry.proto']:
    specification = importlib.util.find_spec(package)
    for directory in specification.submodule_search_locations or []:
        inputs.extend(path for path in Path(directory).rglob('*') if path.is_file() and path.suffix in ('.py', '.so', '.pyd'))
store = DESTINATION / 'loaded-inputs'; store.mkdir()
loaded = []
for source in sorted(set(inputs)):
    sha = digest(source); target = store / sha
    if not target.exists():
        shutil.copy2(source, target)
    assert digest(target) == sha
    loaded.append({'path': str(source), 'sha256': sha, 'contents': 'loaded-inputs/' + sha})
(DESTINATION / 'LOADED-INPUTS.json').write_text(json.dumps(loaded, indent=2) + '\n')
result = {'runtime': RUNTIME, 'raw_records': counts, 'provider_records': len(provider_records),
          'additional_input_records': len(loaded), 'unique_additional_inputs': len(list(store.iterdir())),
          'actual_final_launches': len(groups), 'development_launches': 72,
          'raw_attempt_folders': reconciliation['raw_attempt_folders'], 'copied_attempts': len(copied),
          'scope': 'Declared diagnostic source/provider/tool/decoder inputs and exact filesystem observations; no transient, undeclared effect, OS-library or shipping proof.'}
(DESTINATION / 'RETENTION.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'archive': str(DESTINATION), **result}), flush=True)
