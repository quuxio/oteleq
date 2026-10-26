"""Isolate the source-build2 SDK-manifest path binding from compiler execution."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'source'))
from otelc import llvm_backend, native_build, native_gate
from otelc.config import Policy

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

policy = Policy.parse({'schema_version': 3, 'languages': ['c']})
with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
    directory = Path(temporary)
    (directory / 'plugin').mkdir()
    (directory / 'gate').mkdir()
    (directory / 'sdk').mkdir()
    sdk_file = directory / 'sdk/unrelated.txt'
    sdk_file.write_text('this is not an SDK build manifest\n')
    library = {'path': '/literal/runtime.so', 'sha256': 'a' * 64}
    native = {'schema_version': 1, 'kind': 'otelc.native-build', 'profile': 'llvm22-native-launch-v1',
        'language': 'c', 'root': '/literal/application', 'policy': policy.data, 'policy_sha256': digest(policy.data),
        'selection_sha256': digest({key: policy.data[key] for key in ('sources', 'functions')}),
        'inputs': [], 'sdk_library': library, 'products': [{'path': str(directory / name)} for name in ('plain', 'instrumented')],
        'commands': [], 'source_complete': False}
    plugin = {'schema_version': 1, 'kind': 'otelc.llvm-plugin', 'source_complete': False,
              'profile': llvm_backend.SOURCE_PROFILE, 'probe_abi': 'otelc.function.v2'}
    gate = {'schema_version': 1, 'kind': 'otelc.native.exec-gate', 'source_complete': False,
            'executable': {'path': str(directory / 'gate/otelc-exec-gate')}, 'source': {'path': str(native_gate.SOURCE)}}
    fixed = {'native': directory / 'native-build.json', 'plugin': directory / 'plugin' / llvm_backend.MANIFEST,
             'gate': directory / 'gate/gate.json'}
    for name, record in (('native', native), ('plugin', plugin), ('gate', gate)):
        fixed[name].write_text(json.dumps(record))
    manifest = {'schema_version': 2, 'kind': 'otelc.native.source-build', 'profile': 'native-owned-v1',
                **{key: native_gate.identity(path) for key, path in fixed.items()},
                'sdk': native_gate.identity(sdk_file), 'source_complete': False}
    (directory / native_build.MANIFEST).write_text(json.dumps(manifest))
    with (patch.object(native_build, 'sdk', return_value={'library': library}) as sdk,
          patch('otelc.native_launch.verify'), patch.object(native_gate.Product, 'verify')):
        native_build.verify(directory, policy)
    result = {'head': '3c8269eb62224c4f0bdd69ea3e7b63a19354b841', 'accepted': True,
              'bound_sdk_record': sdk_file.name, 'required_fixed_sdk_record': 'native-sdk-build.json',
              'scope': 'SDK-record path-binding unit boundary; SDK/build/plugin/gate validity trusted via stubs; actual source-build metadata files/identity readers used; no compiler or application launched'}
(ROOT / 'sdk-record-binding-probe.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
