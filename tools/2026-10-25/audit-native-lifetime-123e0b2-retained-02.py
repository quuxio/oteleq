"""Audit historical captured bytes; never recertify original host file identity."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile

BASE = Path('/Users/sclarke/github/oteleq-qualification')
BUILD = BASE / '2026-10-25/native-lifetime-build'
SOURCE = BASE / 'work/oteleq-native-lifetime-promotion'
ROOT = BUILD / 'hosted-123e0b2-retained/native-lifetime-evidence'
RUNNER = Path('/home/runner/work/_temp/native-lifetime-evidence')
OUT = BUILD / 'retained-audit-123e0b2-55d5476-02'
OUT.mkdir()
(OUT / 'controller.py').write_bytes(Path(__file__).read_bytes())
sys.path.insert(0, str(SOURCE / 'tests'))
import qualify_native_lifetimes as driver
import native_lifetime_audit as raw
import native_prepared_receipt as records


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


index = records.read(BUILD / 'hosted-123e0b2-retained-index.json')
assert sha256(BUILD / 'hosted-123e0b2-artifact.zip') == index['archive_sha256']
held = {}
for name, expected in index['selected_sha256'].items():
    path = ROOT.parent / name
    assert sha256(path) == expected
    held[str(path)] = records.identity(path)
original = records.read(ROOT / 'qualification.json')
assert original['consumer_source'] == '123e0b2c154cc85a8e8726b372fb6f9d4ada5be3'
assert original['sdk_source'] == driver.SDK_HEAD
records.same(original['cases'], [dict(name=name, language=language, difference=difference)
                                for name, language, difference in driver.CASES])
records.same(original['routes'], ['generated', 'framework', 'replay', 'detached', 'scalar-reduction'])

# Sources are read from fixed archive members and matched to local Git objects.
# Recorded runner inode/UID/timestamp values remain historical data.
source_facts = records.read(ROOT / 'original-source-facts.json')
catalogues = {}
for role, repo, head in (
        ('consumer', SOURCE, original['consumer_source']),
        ('provider', Path('/Users/sclarke/github/otelc-qualification/work/rust-drop-engine'), driver.SDK_HEAD)):
    expected_root = '/home/runner/work/oteleq/oteleq/' + role
    expected = source_facts[expected_root]
    lines = subprocess.check_output(['git', 'ls-tree', '-rz', '--full-tree', head], cwd=repo)
    tree = {}
    for row in lines.rstrip(b'\0').split(b'\0'):
        metadata, name = row.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        assert kind == 'blob'
        tree[name.decode()] = (mode, oid)
    assert set(expected) == set(tree)
    seen = set()
    with tarfile.open(ROOT / (role + '-source.tar')) as archive:
        for member in archive:
            if member.isdir(): continue
            assert member.isfile() and member.name in tree and member.name not in seen
            body = archive.extractfile(member).read()
            mode, oid = tree[member.name]
            assert hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == oid
            assert hashlib.sha256(body).hexdigest() == expected[member.name]['sha256']
            assert len(body) == expected[member.name]['size']
            # Git tar.umask adds archive group-write bits; these are not live file modes.
            assert member.mode & 0o111 == int(mode, 8) & 0o111
            assert member.mode & ~0o777 == 0
            seen.add(member.name)
    assert seen == set(tree)
    catalogues[role] = {'head': head, 'files': len(seen), 'tar_sha256': sha256(ROOT / (role + '-source.tar'))}

sdk_products = records.read(ROOT / 'sdk-original-products.json')
sdk_hashes = {}
with zipfile.ZipFile(BUILD / 'hosted-123e0b2-artifact.zip') as archive:
    for name in ('native-sdk-build.json', 'libotelc_native_runtime.so'):
        expected = sdk_products['/home/runner/work/_temp/native-lifetime-sdk/' + name]
        with archive.open('native-lifetime-sdk/' + name) as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        assert digest == expected['sha256']
        sdk_hashes[name] = digest

case_languages = {name: language for name, language, _ in driver.CASES}
actual = {}
copied = []
for request_path in sorted(ROOT.rglob('native-runtime/native-request.json')):
    folder = request_path.parent.parent
    relative = folder.relative_to(ROOT)
    assert relative.parts[0] in case_languages
    request = records.read(request_path)
    launch = request['launch_id']
    assert type(launch) is str and re.fullmatch(r'[0-9a-f]{32}', launch)
    if request['runtime'] != str(RUNNER / relative / 'native-runtime'):
        assert relative.parts[:3] == ('c-state', 'shrinking', 'original')
        copied.append(folder)
        continue
    assert launch not in actual
    actual[launch] = folder
assert len(actual) == 64
assert len(copied) == 4
assert set(actual) == set(original['audit']['records'])
for launch, folder in actual.items():
    row = original['audit']['records'][launch]
    request = records.read(folder / 'native-runtime/native-request.json')
    application = records.read(folder / 'native-runtime/native-application-start.json')
    records.same(row, {'pid': application['pid'], 'folder': str(RUNNER / folder.relative_to(ROOT)),
                       'plain': request['plain']})


class HistoricalAudit:
    """Read every raw receipt, while keeping copied launch denominators unique."""

    def __init__(self) -> None:
        self.seen = {}
        self.observations = Counter()
        self.copied_observations = 0

    def attempt(self, report: Path, folder: Path, entry: dict, lane: str, witness,
                arguments: tuple[int, ...], *, function: str) -> None:
        name = report.relative_to(ROOT).parts[0]
        assert entry['language'] == case_languages[name] and function == 'selected'
        request = records.read(folder / 'native-runtime/native-request.json')
        launch = request['launch_id']
        assert launch in actual and request['plain'] is (lane == 'baseline')
        observed = raw.verify(folder, entry, witness, plain=lane == 'baseline', function=function)
        records.same(self.seen.setdefault(launch, observed), observed)
        self.observations[name] += 1
        self.copied_observations += int(folder != actual[launch])


audit = HistoricalAudit()
reports = sorted(ROOT.rglob('report.json'))
assert len(reports) == 17
for path in reports:
    relative = path.relative_to(ROOT)
    assert relative.parts[0] in case_languages
    expected = (5,)
    if relative.parts[:2] == ('c-state', 'shrinking'):
        assert relative.parts[2] in ('original', 'confirmation', 'trial-0000', 'workspace')
        if relative.parts[2] != 'original': expected = (0,)
    driver.check_report(path, relative.parts[0] == 'c-state', audit, expected=expected)
assert set(audit.seen) == set(actual)
assert audit.observations == {'c-completed': 16, 'cpp-completed': 16, 'c-state': 36}
assert audit.copied_observations == 4
assert sum(value is not None for value in audit.seen.values()) == 32
for name, expected in held.items():
    records.same(records.identity(Path(name)), expected)

result = {
    'status': 'pass for historical captured-byte audit', 'run': index['run'],
    'executor': original['consumer_source'],
    'verifier': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE).decode().strip(),
    'archive_sha256': index['archive_sha256'], 'source_catalogues': catalogues,
    'sdk_original_product_hashes': sdk_hashes,
    'actual_application_launch_records': len(actual), 'instrumented_raw_receipts': 32,
    'reports': len(reports), 'observations': dict(audit.observations),
    'copied_observations_not_new_launches': audit.copied_observations,
    'selected_evidence_files_preserved': len(held),
    'new_application_launches': 0, 'compiler_builds': 0, 'sdk_builds': 0,
    'scope': 'Strict original declared typed return/state/errno/input observations plus all original/copy raw function/lifetime protobuf and closed SDK health. Source tar contents match Git objects and recorded hashes; original SDK product bytes match the original captured hashes.',
    'limits': 'Historical runner OS ownership and inode/UID/timestamps are not recertified on this host. This is not execution of the newer raw-refusal or promotion driver, startup/live/zero/censored/exception or shipping qualification. Exact55 hosted gates and current source review remain separate.',
}
(OUT / 'review.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
