"""Replace real bindings at either independent I/O boundary during preparation."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-3af8610'
sys.path[:0] = [str(SOURCE), str(SOURCE / 'tests')]
from otelc import file_inputs, java, prepared_java, witness
from otelc.config import Policy
from test_prepared_java import binding
from test_witness import SOURCE as APPLICATION

mode = sys.argv[1]
assert mode in ('snapshot', 'late')
proof = ROOT / ('replace-' + mode);proof.mkdir()
source = proof / 'Harness.java';source.write_text(APPLICATION)
classes = proof / 'classes';classes.mkdir()
subprocess.run([java.executable('javac'), '-d', str(classes), str(source)], check=True)
manifest = proof / 'application.json'
manifest.write_text(json.dumps({'schema_version': 1, 'main_class': 'Harness', 'classpath': ['classes'],
    'bindings': {owner: binding(source, classes / (owner + '.class'), 'src/Harness.java')
                 for owner in ('Harness', 'Work')}}))
application = prepared_java.PreparedApplication.load(manifest)
declarations = {role: {'owner': 'Work' if role == 'target' else 'Harness', 'name': role,
    'descriptor': '()V' if role == 'rendezvous' else '(I)I'} for role in witness.ROLES}
bindings = proof / 'bindings.json'
witness.compile_bindings(application, declarations, bindings)
content = bindings.read_bytes();(proof / 'original-bindings.json').write_bytes(content)
digest = hashlib.sha256(content).hexdigest()
policy = Policy.parse({'schema_version': 3, 'languages': ['java'],
    'sources': {'include': ['src/**']}, 'functions': {'include': ['Work.target(*)']},
    'traces': {'enabled': True, 'sample_ratio': 1.0}})
temporary = Path(tempfile.mkdtemp(prefix='oteleq-snapshot-', dir='/tmp')).resolve()
(temporary / '.review-owner').write_text(str(os.getpid()))
(proof / 'runtime-path.txt').write_text(str(temporary))
runtime = temporary / 'r';runtime.mkdir(mode=0o700)
replaced = []


def replace():
    bindings.unlink();os.mkfifo(bindings, 0o600)
    replaced.append(True)
    print('validated-binding-replaced-with-fifo', flush=True)


checked = file_inputs.checked_file
identity = prepared_java.file_identity


def after_snapshot(path, **options):
    value = checked(path, **options)
    if Path(path) == bindings and options.get('include_content') and not replaced:replace()
    return value


def after_identity(path):
    value = identity(path)
    if Path(path) == bindings and not replaced:replace()
    return value


owner, name, replacement = (file_inputs, 'checked_file', after_snapshot) if mode == 'snapshot' else (prepared_java, 'file_identity', after_identity)
launch, refused = None, False
with patch.object(owner, name, side_effect=replacement):
    try:
        launch = prepared_java.prepare(application, policy, runtime, diagnostic_profile=True, witness_bindings=bindings)
    except ValueError:
        refused = True
assert replaced
metadata = json.loads((runtime / 'witness.json').read_text())
assert metadata['bindings_sha256'] == digest
if launch is not None:
    try:launch.verify_inputs()
    except ValueError:refused = True
assert refused
assert source.read_text() == APPLICATION
print('source-change-refused-without-application-execution', flush=True)
