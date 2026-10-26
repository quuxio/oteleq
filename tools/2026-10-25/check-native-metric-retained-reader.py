"""Exercise retained preparation guards against preserved altered JSON copies."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

BASE = Path('/Users/sclarke/github/oteleq-qualification')
ROOT = BASE / '2026-10-25/native-metric-controls/hosted-9f90307'
CONTROLLER = BASE / '2026-10-25/audit-native-metric-captures-03.py'


def main() -> None:
    output = ROOT / 'retained-reader-negative-controls-03'
    output.mkdir()
    spec = importlib.util.spec_from_file_location('native_metric_retained_reader', CONTROLLER)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    index = reader.records.read(ROOT / 'c-11-selected-index-02.json')
    root = Path(index['root']) / 'native-metric-evidence'
    original = reader.records.read(root / 'qualification.json')
    matches = [row for row in original['audit']['records'].values()
               if not row['plain'] and '/normal/comparison/' in row['folder']]
    row = matches[0]
    folder = root / Path(row['folder']).relative_to(reader.RUNNER)
    report = reader.records.read(folder.parent.parent / 'report.json')
    entry, = [entry for entry in report['inventory'] if entry['status'] == 'ready']
    runtime = folder / 'native-runtime'
    prepared = runtime / 'native-prepared.json'
    started = runtime / 'oteleq-native-start.json'
    controls = [
        ('missing-producer', prepared, lambda value: value['producer'].pop()),
        ('forged-producer-hash', prepared, lambda value: value['producer'][0].update(sha256='f' * 64)),
        ('foreign-producer-path', prepared, lambda value: value['producer'][0].update(path='/foreign.py', resolved_path='/foreign.py')),
        ('reordered-producers', prepared, lambda value: value['producer'].reverse()),
        ('extra-prepared-field', prepared, lambda value: value.update(accepted=True)),
        ('foreign-interpreter-spelling', prepared, lambda value: value.update(interpreter_spelling='/foreign/python')),
        ('request-digest', prepared, lambda value: value.update(request_sha256='0' * 64)),
        ('plan-digest', prepared, lambda value: value.update(plan_sha256='0' * 64)),
        ('start-pid', started, lambda value: value['application'].update(pid=value['application']['pid'] + 1)),
        ('start-record-hash', started, lambda value: value['records'][0].update(sha256='0' * 64)),
        ('start-record-path', started, lambda value: value['records'][0].update(path='/foreign.json', resolved_path='/foreign.json')),
        ('start-record-mode', started, lambda value: value['records'][0].update(mode=0o100644)),
        ('missing-start-record', started, lambda value: value['records'].pop()),
        ('extra-start-field', started, lambda value: value.update(accepted=True)),
    ]
    rejected = []
    real_read = reader.records.read
    with zipfile.ZipFile(index['archive']) as bundle:
        audit = reader.HistoricalAudit(root, bundle, original, '11')
        audit.process(folder, entry, False, 5)
        for label, path, mutate in controls:
            changed = copy.deepcopy(real_read(path))
            mutate(changed)
            captured = output / (label + '.json')
            captured.write_text(json.dumps(changed, indent=2) + '\n')

            def read(candidate: Path) -> dict:
                return real_read(captured if candidate == path else candidate)

            try:
                with patch.object(reader.records, 'read', read):
                    audit.process(folder, entry, False, 5)
            except (AssertionError, ValueError):
                rejected.append(label)
            else:
                raise AssertionError('altered preparation record accepted: ' + label)
    assert len(rejected) == len(set(rejected)) == 14
    for name, value in index['files'].items():
        assert reader.file_hash(Path(index['root']) / name) == value['sha256']
    result = {'status': 'pass', 'controller': str(CONTROLLER),
        'controller_sha256': hashlib.sha256(CONTROLLER.read_bytes()).hexdigest(),
        'positive_original_record': row['folder'], 'rejected': rejected,
        'preserved_altered_json_copies': len(rejected), 'original_files_held': len(index['files']),
        'new_application_launches': 0, 'compiler_builds': 0, 'sdk_builds': 0,
        'scope': 'Preparation/start component guards use preserved altered JSON through an explicit reader seam. No historical operating-system facts or absent interpreter bytes are recertified.'}
    (output / 'review.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
