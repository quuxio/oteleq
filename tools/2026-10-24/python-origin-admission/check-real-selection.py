"""Check the independent selector against genuine native entry/loader captures."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
SDK = ROOT.parent / 'python-origin-scope-review-b74ed97/source-b74ed97'
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-origin-admission')
sys.path[:0] = [str(SDK), str(SDK / 'tests'), str(REPO / 'adapters/generation'), str(REPO / 'examples')]

from ci import build_python_inputs as tooling
from otelc import python_origin_journal as sdk_journal
from python_input_support import NativeInputCase
import python_origin
import python_selection


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    output = ROOT / ('native-selection-' + sys.argv[1])
    output.mkdir(mode=0o700)
    NativeInputCase.setUpClass()
    NativeInputCase.tool = tooling.build(origin_entry=True)
    assert json.loads((NativeInputCase.tool.parent / 'build.json').read_bytes())['inputs']['origin_chain']['available']
    result = []
    for plain in (True, False):
        folder = output / ('plain' if plain else 'instrumented-callback')
        folder.mkdir(mode=0o700)
        application = folder / 'application'; application.mkdir(mode=0o700)
        target = application / 'target.py'
        target.write_text('''GLOBAL = 10
def chosen(value):
    global GLOBAL
    GLOBAL += value
    return GLOBAL
class Counter:
    def __init__(self,value): self.value=value
    def apply(self,value): self.value+=value; return self
def create(value): return Counter(value)
''')
        body = '''from target import chosen,create
c=create(5); c.apply(2)
r=create(3).apply(1)
print(chosen(7),c.value,r.value)
'''
        stock = subprocess.run([sys.executable, '-B', '-c', body], cwd=application,
                               capture_output=True, check=True, timeout=15)
        assert (stock.stdout, stock.stderr) == (b'17 7 4\n', b'')
        setup = '' if plain else f'''import sys,_otelc_inputs as native
def encode(code,*,marker=None):return native.encode(code)
def observer(code,offset):
    if code.co_filename=={str(target)!r} and code.co_name in ('chosen','create','apply'):
        native.observe(code,offset)
assert native.bind(observer,encode) is True
sys.monitoring.use_tool_id(3,'independent-selected-source')
sys.monitoring.register_callback(3,sys.monitoring.events.PY_START,observer)
sys.monitoring.set_events(3,sys.monitoring.events.PY_START)
'''
        entry = application / 'entry.py'; entry.write_text(setup + body)
        source = python_selection.freeze(target)
        selected = tuple(python_selection.Selection(source, name, line) for name, line in
                         [('chosen', 2), ('Counter.apply', 8), ('create', 9)])
        intent = {'python_version': sys.hexversion, 'optimisation': 0, 'plain': plain,
                  'source': {'path': str(target), 'device': source.device, 'inode': source.inode,
                             'mtime_ns': source.mtime_ns, 'mode': source.mode, 'sha256': source.sha256},
                  'selected': [{'qualname': item.qualname, 'line': item.line} for item in selected]}
        expected_path = folder / 'expected.json'
        expected_path.write_text(json.dumps(intent, indent=2) + '\n'); expected_path.chmod(0o600)
        before = {str(path): sha(path) for path in (entry, target)}
        before[str(expected_path)] = sha(expected_path)
        case = NativeInputCase(); case.root, case.number = folder, 0
        status, stdout, stderr, path, pid = case.launch(['-B', str(entry)], origin_root=application)
        assert (status, stdout, stderr) == (stock.returncode, stock.stdout, stock.stderr)
        journal = python_origin.read(path, pid)
        coverage = python_selection.verify(journal, selected, python_version=sys.hexversion, optimisation=0, plain=plain)
        assert len(coverage) == 3 and all(len(row.matches) == 1 for row in coverage)
        assert all((row.matches[0].sdk is None) == plain for row in coverage)
        independent = sdk_journal.read(path, expected_pid=pid)
        assert independent.capture_complete and len(independent.sdk_joins) == (0 if plain else 3)
        refusals = 0
        for chosen, kwargs in [((replace(selected[0], source=replace(source, inode=source.inode + 1)),), {}),
                               ((replace(selected[0], qualname='unexecuted'),), {}),
                               (selected, {'optimisation': 1}), (selected, {'plain': not plain})]:
            try:
                python_selection.verify(journal, chosen, **{'python_version': sys.hexversion,
                                        'optimisation': 0, 'plain': plain, **kwargs})
            except ValueError:
                refusals += 1
            else:
                raise AssertionError('Altered independent intent was accepted')
        assert refusals == 4 and all(sha(Path(name)) == digest for name, digest in before.items())
        result.append({'lane': folder.name, 'actual_pid': pid, 'original_output_status_preserved': True,
                       'source_frozen_before_launch': True, 'source_preserved': True, 'raw_journal_sha256': sha(path),
                       'expected_manifest_sha256': before[str(expected_path)],
                       'coverage': [{'qualname': row.selection.qualname, 'line': row.selection.line,
                                     'source_sha256': row.selection.source.sha256,
                                     'matches': [asdict(match) for match in row.matches]} for row in coverage],
                       'altered_intent_refusals': refusals})
    metadata = json.loads((ROOT.parent / 'python-origin-scope-review-b74ed97/source-b74ed97.json').read_bytes())
    assert all(sha(SDK / name) == digest for name, digest in metadata['files'].items())
    value = {'python': sys.version, 'sdk_head': metadata['head'], 'sdk_source_files_preserved': len(metadata['files']),
             'selector_sha256': sha(REPO / 'adapters/generation/python_selection.py'), 'attempts': result,
             'scope': 'Independent native selected-source component; callback harness is not public provider or SDK telemetry admission'}
    (output / 'result.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'python': sys.version.split()[0], 'applications': len(result), 'selected_callables_each': 3,
                      'altered_intent_refusals': sum(row['altered_intent_refusals'] for row in result),
                      'sdk_sources_preserved': len(metadata['files'])}))


if __name__ == '__main__':
    main()
