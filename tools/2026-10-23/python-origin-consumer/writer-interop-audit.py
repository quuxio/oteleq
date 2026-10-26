"""Recheck retained native writer bytes; start no application or SDK."""

import hashlib
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source-d4c663d'
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import python_origin
import python_journal

receipt = json.loads((BASE / 'writer-interop.json').read_text())
rows = []
for run in receipt['runs']:
    folder = BASE / ('writer-' + run['mode'])
    actual = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir() if path.is_file()}
    assert actual == run['raw_sha256']
    value = python_origin.read(folder / 'inputs.journal', run['writer_pid'])
    source, root, execution, *tail = value.records
    assert type(source) is python_journal.SourceRecord
    assert source.sha256 == run['inputs'][str(folder / 'entry.py')]
    assert source.kind == (3 if 'loader' in run['mode'] else 1)
    assert root.input_sequence == source.sequence == 1
    assert root.descriptor.record.python_version == execution.python_version == 0x030c0ff0
    assert (root.identity, root.transaction, root.route) == (77, 90, 2 if 'loader' in run['mode'] else 1)
    assert execution.root == 77 and execution.identity == 91 and execution.member == 9
    if run['mode'].startswith('on-'):
        code, join = tail
        assert code.identity == join.sdk == 1 and join.origin == execution.identity
    else:
        assert not tail
    assert value.capture_complete and value.comparison_steps == run['comparison_steps']
    rows.append({'mode': run['mode'], 'pid': run['writer_pid'], 'raw_files': len(actual), 'verified': True})
version = '.'.join(map(str, sys.version_info[:3]))
result = {'python': version, 'reader_source': str(SOURCE), 'runs': rows,
          'raw_manifest_sha256': hashlib.sha256((BASE / 'writer-interop.json').read_bytes()).hexdigest(),
          'new_processes': 0, 'authentic_origin_qualification': False}
(BASE / ('writer-audit-' + version + '.json')).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'python': version, 'verified_native_journals': len(rows), 'new_processes': 0}))
