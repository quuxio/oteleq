"""Independently compare fixed native launch edges on unchanged candidate code."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
sys.path.insert(0, str(SOURCE))
from ci import build_python_inputs
from otelc.config import Policy
from otelc import python_input_journal as journal
from otelc import python_recipe as recipe


def main():
    driver = build_python_inputs.build()
    policy = Policy.parse({'schema_version': 3, 'languages': ['python']})
    application = '''import json,sys
sys.stdout.buffer.write(bytes([0,255,10]))
sys.stderr.buffer.write(bytes([1,255,10]))
print(json.dumps({'argv':sys.argv,'orig_argv':sys.orig_argv,
'file':__file__,'name':__name__,'back':sys._getframe().f_back is None,
'spec':None if __spec__ is None else __spec__.name,
'optimize':sys.flags.optimize,'encoding':sys.stdout.encoding},sort_keys=True))
raise SystemExit(7)
'''
    rows = []
    with tempfile.TemporaryDirectory(prefix='native-recipe-edges-', dir=ROOT) as temporary:
        base = Path(temporary)
        app = base / 'app'
        runtime = base / 'runtime'
        app.mkdir()
        runtime.mkdir(mode=0o700)
        entry = app / 'café entry.py'
        entry.write_text(application)
        link = app / 'linked entry.py'
        link.symlink_to(entry.name)
        package = app / 'package'
        package.mkdir()
        (package / '__init__.py').write_text('')
        (package / '__main__.py').write_text(application)
        settings = {'PYTHONOPTIMIZE': '1', 'PYTHONHASHSEED': '17',
                    'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}
        with patch.dict(os.environ, settings):
            for label, selected, module in (
                    ('unicode-source', './café entry.py', None),
                    ('symlink-source', './linked entry.py', None),
                    ('package-module', None, 'package')):
                original = recipe.request(policy, runtime, root=app, entry=selected,
                    module=module, arguments=('', '--switch', 'café'), plain=True)
                plan = recipe.resolve_plan(original)
                recipe.verify(original, plan)
                plain = subprocess.run([plan['python'], *plan['native_arguments']],
                    cwd=plan['cwd'], capture_output=True, timeout=15)
                path = runtime / (label + '.journal')
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    candidate = subprocess.Popen(recipe.native_command(original, driver, descriptor),
                        cwd=plan['cwd'], pass_fds=(descriptor,),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                finally:
                    os.close(descriptor)
                try:
                    out, err = candidate.communicate(timeout=15)
                finally:
                    if candidate.poll() is None:
                        candidate.kill()
                        candidate.wait(timeout=5)
                assert plain.returncode == 7
                assert (candidate.returncode, out, err) == (
                    plain.returncode, plain.stdout, plain.stderr), label
                receipt = journal.read(path, expected_pid=candidate.pid)
                assert receipt.complete is (module is None)
                if module is None:
                    assert len(receipt.sources) == 1
                    assert receipt.sources[0].content == application.encode()
                recipe.verify(original, plan)
                assert entry.read_text() == application
                rows.append({'case': label, 'exit': candidate.returncode,
                    'actual_candidate_pid': candidate.pid,
                    'raw_stdout_sha256': hashlib.sha256(out).hexdigest(),
                    'raw_stderr_sha256': hashlib.sha256(err).hexdigest(),
                    'channels_identical': True, 'source_preserved': True,
                    'entry_journal_complete': receipt.complete})
    index = json.loads((ROOT / 'source.json').read_text())
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == expected
               for name, expected in index['files'].items())
    result = {'head': index['commit'], 'interpreter': sys.version,
        'cases': rows, 'sources_preserved': len(index['files']),
        'scope': 'Three extra paired raw native launch checks; not SDK/provider qualification.'}
    (ROOT / 'launch-edges.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
