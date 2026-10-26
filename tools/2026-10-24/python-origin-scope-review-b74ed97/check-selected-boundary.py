"""Outside loader exclusion cannot confer source membership on selected code."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-b74ed97'
sys.path[:0] = [str(SOURCE), str(SOURCE / 'tests')]

from ci import build_python_inputs as tooling
from otelc import python_origin_journal as journal
from python_input_support import NativeInputCase


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    output = ROOT / ('selected-boundary-' + sys.argv[1])
    output.mkdir(mode=0o700)
    NativeInputCase.setUpClass()
    NativeInputCase.tool = tooling.build(origin_entry=True)
    assert json.loads((NativeInputCase.tool.parent / 'build.json').read_bytes())['inputs']['origin_chain']['available']
    controls = []
    for name, outside, selected in (('inside-selected', False, True), ('outside-unselected', True, False), ('outside-selected', True, True)):
        folder = output / name
        folder.mkdir(mode=0o700)
        application = folder / 'application'
        application.mkdir(mode=0o700)
        target = (folder if outside else application) / 'target.py'
        target.write_text('def chosen(value):\n    return value*2+3\n')
        entry = application / 'entry.py'
        body = f'''import _frozen_importlib_external as external
for index in range(3):
    code=external.SourceFileLoader('target',{str(target)!r}).get_code('target')
    namespace={{}}
    exec(code,namespace)
    print(namespace['chosen'](7),namespace['chosen'](8))
'''
        stock = subprocess.run([sys.executable, '-B', '-c', body], capture_output=True, check=True, timeout=15)
        setup = f'''import sys,_otelc_inputs as native
def encode(code,*,marker=None):return native.encode(code)
def observer(code,offset):
    if {selected!r} and code.co_name=='chosen':native.observe(code,offset)
assert native.bind(observer,encode) is True
sys.monitoring.use_tool_id(3,'independent-root-boundary')
sys.monitoring.register_callback(3,sys.monitoring.events.PY_START,observer)
sys.monitoring.set_events(3,sys.monitoring.events.PY_START)
'''
        entry.write_text(setup + body)
        before = {str(path): sha(path) for path in (entry, target)}
        case = NativeInputCase()
        case.root, case.number = folder, 0
        status, stdout, stderr, path, pid = case.launch(['-B', str(entry)], origin_root=application)
        assert (status, stdout, stderr) == (stock.returncode, stock.stdout, stock.stderr)
        value = journal.read(path, expected_pid=pid)
        assert value.capture_complete == (not outside or not selected)
        assert len([root for root in value.roots if root.route == 2]) == (0 if outside else 3)
        assert len(value.sdk_joins) == (3 if selected and not outside else 0)
        assert all(sha(Path(name)) == digest for name, digest in before.items())
        controls.append({'case': name, 'actual_pid': pid, 'original_output_status_preserved': True,
                         'loader_roots': len([root for root in value.roots if root.route == 2]),
                         'sdk_code_joins': len(value.sdk_joins), 'capture_complete': value.capture_complete,
                         'capture_failures': value.capture_failures, 'source_preserved': True,
                         'raw_journal_sha256': sha(path)})
    manifest = json.loads((ROOT / 'source-b74ed97.json').read_bytes())
    assert all(sha(SOURCE / name) == digest for name, digest in manifest['files'].items())
    result = {'head': manifest['head'], 'python': sys.version, 'source_files_preserved': len(manifest['files']),
              'controls': controls, 'scope': 'Native selected-root component; no public provider admission'}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
