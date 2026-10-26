"""Check compiler manifests with the frozen replacement SDK's public loader only."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

root = Path(__file__).resolve().parent
sdk = Path('/Users/sclarke/github/oteleq-qualification/2026-10-21/java-diagnostics-760a526/provider')
sys.path.insert(0, str(sdk))
from otelc.prepared_java import PreparedApplication

def source_identity():
    return {path.relative_to(sdk).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sdk.rglob('*') if path.is_file()}

before = source_identity()
manifests = list((root / 'corpus').rglob('prepared-application.json'))
assert manifests
unique = {hashlib.sha256(path.read_bytes()).hexdigest(): path for path in manifests}
counts = []
for path in unique.values():
    application = PreparedApplication.load(path)
    identity = application.input_identity()
    counts.append({'manifest': str(path.relative_to(root)), 'bindings': len(application.bindings),
                   'class_files': len(identity['classpath']), 'sources': len(identity['sources'])})
controls = []
original = json.loads(next(iter(unique.values())).read_text())
name = next(iter(original['bindings']))
with tempfile.TemporaryDirectory(prefix='oteleq-prepared-controls-') as temporary:
    path = Path(temporary) / 'application.json'
    for fault in ('source_sha256', 'class_sha256', 'provenance', 'main'):
        data = copy.deepcopy(original)
        if fault == 'main': del data['bindings'][data['main_class']]
        else: data['bindings'][name][fault] = '' if fault == 'provenance' else '0' * 64
        path.write_text(json.dumps(data))
        try:
            PreparedApplication.load(path)
        except ValueError:
            controls.append(fault)
        else:
            raise AssertionError('invalid prepared binding passed: ' + fault)
assert before == source_identity()
result = {'sdk_commit': '760a5264bd4c64ecc4a56bf747fb819f085226fa',
          'scope': 'public prepared manifest loader only; no application JVM or SDK runtime qualification',
          'retained_manifests': len(manifests), 'unique_manifests_loaded': len(unique),
          'class_bindings_loaded': sum(item['bindings'] for item in counts),
          'negative_controls': controls, 'sdk_files_preserved': len(before),
          'sdk_source_sha256': before, 'manifests': counts}
(root / 'prepared-loader.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key not in ('sdk_source_sha256', 'manifests')}))
