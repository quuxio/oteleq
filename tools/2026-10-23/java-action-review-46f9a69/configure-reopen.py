"""Fault-inject replacement after the bindings identity was actually read."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parent
source = root / 'source-46f9a69'
sys.path[:0] = [str(source), str(source / 'tests')]
from otelc import java, prepared_java, witness
from otelc.config import Policy
from test_prepared_java import binding
from test_witness import SOURCE

proof = root / 'configure-reopen-short'
proof.mkdir()
application_source = proof / 'Harness.java'
application_source.write_text(SOURCE)
classes = proof / 'classes';classes.mkdir()
subprocess.run([java.executable('javac'), '-d', str(classes), str(application_source)], check=True)
manifest = proof / 'application.json'
manifest.write_text(json.dumps({'schema_version': 1, 'main_class': 'Harness', 'classpath': ['classes'],
    'bindings': {owner: binding(application_source, classes / (owner + '.class'), 'src/Harness.java')
                 for owner in ('Harness', 'Work')}}))
application = prepared_java.PreparedApplication.load(manifest)
declarations = {role: {'owner': 'Work' if role == 'target' else 'Harness', 'name': role,
    'descriptor': '()V' if role == 'rendezvous' else '(I)I'} for role in witness.ROLES}
bindings = proof / 'bindings.json'
witness.compile_bindings(application, declarations, bindings)
policy = Policy.parse({'schema_version': 3, 'languages': ['java'],
    'sources': {'include': ['src/**']}, 'functions': {'include': ['Work.target(*)']},
    'traces': {'enabled': True, 'sample_ratio': 1.0}})
runtime_root = Path(tempfile.mkdtemp(prefix='oteleq-reopen-', dir='/tmp')).resolve()
(runtime_root / '.review-owner').write_text(str(os.getpid()))
(proof / 'runtime-path.txt').write_text(str(runtime_root))
runtime = runtime_root / 'r';runtime.mkdir(mode=0o700)
original = prepared_java.file_identity


def replace_after_identity(path):
    identity = original(path)
    if Path(path) == bindings:
        (proof / 'original-bindings.json').write_bytes(bindings.read_bytes())
        bindings.unlink()
        os.mkfifo(bindings, 0o600)
        print('validated-binding-replaced-with-fifo', flush=True)
    return identity


prepared_java.file_identity = replace_after_identity
prepared_java.prepare(application, policy, runtime, diagnostic_profile=True, witness_bindings=bindings)
raise AssertionError('changed bindings reached a prepared launch')
