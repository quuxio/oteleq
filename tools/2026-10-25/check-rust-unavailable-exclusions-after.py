"""Reproduce exclusion precedence across names of one unavailable Rust type."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
output = Path(sys.argv[2])
sys.path[:0] = [str(root), str(root / 'tests')]
from test_rust_lifetimes import RustLifetimeSelectionTests
from otelc import rust_lifetimes
from otelc.config import Policy

fixture = RustLifetimeSelectionTests()
fixture.setUp()
rows = []
try:
    for exclude in ('File', 'std::fs::File', '*File*'):
        data = copy.deepcopy(fixture.policy.data)
        data['lifetimes']['exclude'] = [exclude]
        policy = Policy.parse(data)
        selected = fixture.read(fixture.version_two(), policy)
        unsupported = [value for body in selected['bodies'] for value in body['unavailable_locals']]
        try:
            rust_lifetimes.weave_request(fixture.path, policy, fixture.root, fixture.sources)
        except ValueError as error:
            outcome = {'request_accepted': False, 'error': str(error)}
        else:
            outcome = {'request_accepted': True}
        rows.append({'exclude': exclude, 'compiler_name_selected': policy.selection('lifetimes').accepts('std::fs::File'),
                     'rendered_name_selected': policy.selection('lifetimes').accepts('File'),
                     'unavailable_locals_selected': len(unsupported), **outcome})
    assert [row['unavailable_locals_selected'] for row in rows] == [0, 0, 0]
    assert [row['request_accepted'] for row in rows] == [True, True, True]
finally:
    fixture.doCleanups()
result = {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
          'root': str(root), 'status': 'original exact exclusions now honoured', 'rows': rows,
          'sdk_builds': 0, 'compiler_builds': 0, 'native_application_launches': 0,
          'scope': 'Independent literal common-policy/read/request control only; no end-to-end application claim.'}
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
