"""Exercise fresh loader roots and code-identity refusal through real VM starts."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-bc05006'
sys.path[:0] = [str(SOURCE), str(SOURCE / 'tests')]

from ci import build_python_inputs as tooling
from otelc import python_origin_journal as journal
from python_input_support import NativeInputCase


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    output = ROOT / ('loader-joins-' + sys.argv[1])
    output.mkdir(mode=0o700)
    NativeInputCase.setUpClass()
    NativeInputCase.tool = tooling.build(origin_entry=True)
    metadata = json.loads((NativeInputCase.tool.parent / 'build.json').read_bytes())
    assert metadata['inputs']['origin_chain']['available']
    results = []
    for altered in (False, True):
        folder = output / ('replaced-code' if altered else 'fresh-source')
        folder.mkdir(mode=0o700)
        target = folder / 'target.py'
        target.write_text('def chosen(value):\n    return value*2+3\n')
        body = '''import _frozen_importlib_external as external
path=__file__.replace('original.py','target.py')
for index in range(3):
    code=external.SourceFileLoader('target',path).get_code('target')
    namespace={}
    exec(code,namespace)
    print(namespace['chosen'](7),namespace['chosen'](8))
'''
        if altered:
            body += "namespace['chosen'].__code__=namespace['chosen'].__code__.replace()\nprint(namespace['chosen'](7))\n"
        stock = subprocess.run([sys.executable, '-B', '-c', "__file__=" + repr(str(folder / 'original.py')) + '\n' + body],
                               capture_output=True, check=True, timeout=15)
        setup = '''import sys,_otelc_inputs as native
def encode(code,*,marker=None):return native.encode(code)
def observer(code,offset):
    if code.co_name=='chosen':native.observe(code,offset)
assert native.bind(observer,encode) is True
sys.monitoring.use_tool_id(3,'independent-loader-join')
sys.monitoring.register_callback(3,sys.monitoring.events.PY_START,observer)
sys.monitoring.set_events(3,sys.monitoring.events.PY_START)
'''
        entry = folder / 'original.py'
        entry.write_text(setup + body)
        before = {str(path): sha(path) for path in (entry, target)}
        case = NativeInputCase()
        case.root, case.number = folder, 0
        status, stdout, stderr, path, pid = case.launch(['-B', str(entry)], loader_origins=True)
        assert (status, stdout, stderr) == (stock.returncode, stock.stdout, stock.stderr)
        value = journal.read(path, expected_pid=pid)
        assert value.capture_complete is not altered
        roots = [root for root in value.roots if root.route == 2]
        assert len(roots) == len(value.sdk_joins) == 3
        assert len({sdk for sdk, _ in value.sdk_joins}) == 3
        assert len({root.input_sequence for root in roots}) == 3
        executions = {event.identity: event for event in value.executions}
        assert all(executions[origin].root in {root.identity for root in roots} for _, origin in value.sdk_joins)
        assert all(sha(Path(name)) == digest for name, digest in before.items())
        results.append({'case': folder.name, 'actual_pid': pid, 'original_output_status_preserved': True,
                        'fresh_loader_roots': len(roots), 'sdk_code_joins': len(value.sdk_joins),
                        'capture_complete': value.capture_complete, 'capture_failures': value.capture_failures,
                        'source_preserved': True, 'raw_journal_sha256': sha(path)})
    manifest = json.loads((ROOT / 'source-bc05006.json').read_bytes())
    assert all(sha(SOURCE / name) == digest for name, digest in manifest['files'].items())
    result = {'head': manifest['head'], 'python': sys.version, 'source_files_preserved': len(manifest['files']),
              'controls': results, 'scope': 'Native component and authenticated test callback; actual SDK export is covered separately'}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
