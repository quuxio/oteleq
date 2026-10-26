"""Independent exact-source SDK unit-recipe tests and a system-header control."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest

BASE = Path(__file__).resolve().parent
OWNER = Path('/Users/sclarke/github/otelc-qualification/work/native-build-context')
INDEX = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/native-build-context/source-6bc9ee0.json')
SDK = OWNER / 'build/context-sdk'


def state() -> dict:
    """Verify all frozen source bytes and retain original filesystem identities."""
    value = json.loads(INDEX.read_text())
    result = {}
    paths = [OWNER / name for name in value['files']]
    paths.extend((SDK / 'native-sdk-build.json', SDK / 'libotelc_native_runtime.dylib'))
    for path in paths:
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        name = str(path.relative_to(OWNER))
        if name in value['files']:
            assert checksum == value['files'][name], name
        stat = path.stat()
        result[str(path)] = [checksum, stat.st_dev, stat.st_ino, stat.st_mode,
                             stat.st_uid, stat.st_gid, stat.st_size,
                             stat.st_mtime_ns, stat.st_ctime_ns, stat.st_nlink]
    return result


def main() -> None:
    started = time.monotonic()
    before = state()
    (BASE / 'inputs-before.json').write_text(json.dumps(before, indent=2) + '\n')
    sys.path[:0] = [str(OWNER), str(OWNER / 'tests')]
    from otelc import native_build
    from otelc.config import Policy

    controls = BASE / 'controls'
    controls.mkdir()
    app = controls / 'app'
    app.mkdir()
    include = app / 'include'
    include.mkdir()
    header = include / 'value.h'
    header.write_text('#define ANSWER 3\n')
    source = app / 'main.c'
    source.write_text('#include <value.h>\nint main(void){return ANSWER;}\n')
    recipe = {'schema_version': 1, 'kind': 'otelc.native.unit-recipe', 'assets': [],
              'units': [{'id': 'main', 'role': 'application', 'source': str(source),
                         'language': 'c', 'directory': str(app),
                         'flags': ['-std=c11', '-O1', '-isystem', str(include)],
                         'overlay': None, 'rename_main': False}],
              'link': {'language': 'c', 'directory': str(app), 'flags': []}}
    policy = Policy.parse({'schema_version': 3, 'languages': ['c'],
                           'sources': {'include': ['**']}, 'functions': {'include': ['**']}})
    output = controls / 'compiled'
    native_build.build(policy, 'c', app, [], output, sdk_directory=SDK, recipe=recipe)
    native_build.verify(output, policy)
    record = json.loads((output / 'native-build.json').read_text())
    result = {'header': str(header), 'dependencies': record['dependencies'],
              'recorded_header': str(header) in {row['path'] for row in record['inputs']},
              'applications_started': 0}
    header.write_text('#define ANSWER 9\n')
    try:
        native_build.verify(output, policy)
    except ValueError as exc:
        result['changed_header'] = 'refused'
        result['reason'] = str(exc)
    else:
        result['changed_header'] = 'accepted'
    (BASE / 'system-header-control.json').write_text(json.dumps(result, indent=2) + '\n')

    os.environ['OTELC_NATIVE_SDK_BUILD'] = str(SDK)
    suite = unittest.defaultTestLoader.loadTestsFromName('test_native_units')
    with (BASE / 'focused-tests.stderr').open('w') as log:
        tests = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    assert state() == before, 'Frozen owner source or SDK changed'
    receipt = {'head': json.loads(INDEX.read_text())['head'], 'source_files': 449,
               'source_and_sdk_facts_held': True, 'tests': tests.testsRun,
               'test_failures': len(tests.failures), 'test_errors': len(tests.errors),
               'test_success': tests.wasSuccessful(), 'system_header_control': result,
               'seconds': round(time.monotonic() - started, 3),
               'scope': 'Independent maintained per-unit tests and compile-only altered-header control. No SDK rebuild or full gate.'}
    (BASE / 'controls-result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))
    assert tests.wasSuccessful()


if __name__ == '__main__':
    main()
