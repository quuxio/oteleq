"""Publish only completed exact-revision compiler qualification evidence."""
import hashlib
import json
from pathlib import Path
import platform

root = Path(__file__).resolve().parent
repo = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-provider')
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
runtime = json.loads((root / 'runtime.json').read_text())
result = json.loads((root / 'corpus/qualification.json').read_text())
loader = json.loads((root / 'prepared-loader.json').read_text())
before = json.loads((root / 'provider-before.json').read_text())
after = json.loads((root / 'provider-after.json').read_text())
assert before == after and before['verified_records'] == 7360
assert result['actual_launches'] == result['unique_command_identities'] == 151
assert result['matching_cases'] == 6 and result['same_return_state_differences'] == 2 and result['refusal_controls'] == 7
assert loader['unique_manifests_loaded'] == 151 and loader['class_bindings_loaded'] == 455
assert len(loader['negative_controls']) == 4 and loader['sdk_files_preserved'] == 55
records = {}
for name in ('quux-oteleq', 'oteleq-source.tar', 'runtime.json', 'source', 'corpus', 'load_prepared.py',
             'prepared-loader.json', 'provider-before.json', 'provider-after.json', 'qualification.log'):
    path = root / name
    for item in sorted(path.rglob('*')) if path.is_dir() else [path]:
        assert not item.is_symlink(), item
        if item.is_file(): records[item.relative_to(root).as_posix()] = sha(item)
manifest = root / 'evidence-manifest.json'
manifest.write_text(json.dumps({'schema_version': 1, 'files_sha256': records},indent=2)+'\n')
record = {
 'qualification_schema_version': 1, 'date': '2026-10-21',
 'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
 'platform': {'os': platform.platform(), 'architecture': platform.machine()},
 'runtime': runtime,
 'provider': before,
 'results': result,
 'prepared_loader': {key: loader[key] for key in ('sdk_commit', 'scope', 'retained_manifests',
    'unique_manifests_loaded', 'class_bindings_loaded', 'negative_controls', 'sdk_files_preserved')},
 'evidence': {'retained_files': len(records), 'manifest_sha256': sha(manifest)},
 'checks': [
  'Every repeat checks complete independent receiver, static, result/error and alias/cycle values plus actual decoded selected-function telemetry.',
  'All 155 retained compiler manifests and 467 retained class bindings are independently checked; four copied original shrink attempts do not inflate the 151 actual launches.',
  'Generated, exported and replay suites retain source/class bindings; scalar reduction preserves construction inputs and reduces the intentional static-state difference from seven to zero.',
  'The public replacement-SDK loader accepts all 151 unique manifests and 455 unique class bindings; no application JVM is started by that separate loader check.',
  'All 7360 declared legacy-provider source/product/dependency records and all 55 frozen replacement-SDK source files remain unchanged.'
 ],
 'limits': [
  'Fixed UTF-8 private source-classpath profile with annotation processing disabled; arbitrary classpath/module/project builds remain open.',
  'Source/class hashes and compiler callbacks are trusted local evidence, not a proof against malicious change-and-revert activity.',
  'The JDK module image is hashed; native JDK/OS library identities are not comprehensively covered.',
  'Public prepared-manifest loading does not establish replacement-SDK runtime health, live controls, invocation attribution, shipping artefact equivalence or another platform.'
 ]}
destination = repo / 'docs/qualification/java-compiler-2026-10-21.json'
destination.write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'published_record':str(destination),'evidence_files':len(records),'manifest_sha256':sha(manifest)}))
