"""Check the current retained reader's new actual-CLI binding controls."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
from pathlib import Path
import zipfile


BASE = Path('/Users/sclarke/github/oteleq-qualification')
PATH = BASE / '2026-10-26/audit-native-metric-captures-05.py'
spec = importlib.util.spec_from_file_location('metric_reader', PATH)
assert spec is not None and spec.loader is not None
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
index = reader.records.read(reader.BUILD / 'c-11-selected-index-04.json')
root = Path(index['root']) / 'native-metric-evidence'
original = reader.records.read(root / 'qualification.json')
archive_path = Path(index['archive'])
before = reader.file_hash(archive_path)
assert before == index['archive_sha256']


class ArchiveView:
    """Supply one altered or absent member without changing the original ZIP."""

    def __init__(self, archive: zipfile.ZipFile, mode: str):
        self.archive, self.mode = archive, mode

    def open(self, member: str):
        if member == 'native-metric-evidence/consumer-cli':
            if self.mode == 'missing':
                raise KeyError(member)
            return io.BytesIO(b'altered retained CLI bytes')
        return self.archive.open(member)

    def getinfo(self, member: str):
        return self.archive.getinfo(member)


with zipfile.ZipFile(archive_path) as archive:
    valid = reader.HistoricalAudit(root, archive, original, '11')
    assert valid.products['consumer_cli']['sha256'] == original['consumer_cli_sha256']
    refused = []
    for mode in ('missing', 'altered'):
        try:
            reader.HistoricalAudit(root, ArchiveView(archive, mode), original, '11')
        except (KeyError, ValueError):
            refused.append(mode + '-CLI-member')
        else:
            raise AssertionError('accepted ' + mode + ' retained CLI')
    changed = copy.deepcopy(original)
    changed['consumer_cli_sha256'] = '0' * 64
    try:
        reader.HistoricalAudit(root, archive, changed, '11')
    except ValueError:
        refused.append('changed-declared-CLI-sha256')
    else:
        raise AssertionError('accepted wrong declared CLI digest')
assert reader.file_hash(archive_path) == before
result = {
    'status': 'pass', 'positive_actual_archive': index['archive_sha256'],
    'refused': refused, 'count': len(refused),
    'scope': 'Three extra reader controls for the new actual retained CLI binding; original ZIP unchanged. These are separate from the42 raw OTLP/health mutants.',
    'new_application_launches': 0,
}
out = reader.BUILD / 'c-11-reader-controls-05.json'
assert not out.exists()
out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
