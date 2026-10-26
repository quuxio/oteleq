from pathlib import Path
import hashlib
import json
import os
import sys

root = Path('/private/tmp/otelc-integrated-provider-0419a51-frozen')
manifest_path = root.with_suffix('.json')
manifest = json.loads(manifest_path.read_text())
for label in ['source_sha256', 'products_sha256']:
    for name, expected in manifest[label].items():
        with (root/name).open('rb') as handle:
            assert hashlib.file_digest(handle, 'sha256').hexdigest() == expected, name
actual_dependencies = {}
for folder in (root / '.venv', root / 'adapters/node/node_modules'):
    for path in sorted(folder.rglob('*')):
        name = str(path.relative_to(root))
        if path.is_symlink():
            actual_dependencies[name] = {'symlink': str(path.readlink()), 'resolved': str(path.resolve())}
        elif path.is_file():
            with path.open('rb') as handle:
                actual_dependencies[name] = {'sha256': hashlib.file_digest(handle, 'sha256').hexdigest()}
assert actual_dependencies == manifest['dependencies'], {
    'new': sorted(set(actual_dependencies)-set(manifest['dependencies'])),
    'missing': sorted(set(manifest['dependencies'])-set(actual_dependencies)),
    'changed': [name for name in actual_dependencies.keys() & manifest['dependencies'].keys() if actual_dependencies[name]!=manifest['dependencies'][name]],
}
for path in [root, *root.rglob('*')]:
    if not path.is_symlink():
        assert path.stat().st_mode & 0o222 == 0, path
for name, identity in manifest['tools'].items():
    with Path(identity['path']).open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == identity['sha256'], name
sys.path.insert(0, '/private/tmp/oteleq-http-work/examples')
import otelc_capture
os.environ.update(manifest['environment'])
records = {}
for language in ['c','cpp','rust','python','java','javascript','typescript','go']:
    tools = otelc_capture.selected_tools(root, language)
    records[language] = otelc_capture.artefacts(root, language, tools, rust_backend='compiler')
proof = {'head': manifest['source_commit'], 'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
         'all_source_product_dependency_tool_hashes_match': True, 'read_only': True,
         'dependencies': len(actual_dependencies), 'consumer_artifact_counts': {language:len(values) for language,values in records.items()},
         'consumer_artifacts': records, 'application_launches': 0,
         'scope': 'Structural eight-language consumer-input verification only; behavioural captures belong to oteleq qualification.'}
Path('/private/tmp/oteleq-http-74be0db-provider-verification.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({key:value for key,value in proof.items() if key!='consumer_artifacts'},indent=2))
