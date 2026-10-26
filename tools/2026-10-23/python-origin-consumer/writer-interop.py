"""Actual C writer/data-reader interoperability, not application origins."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent
CONSUMER = BASE / 'source-d4c663d'
PRODUCER = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-origin-pins/source-de188e5')
sys.path[:0] = [str(CONSUMER / 'tests'), str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples')]
import python_origin
from test_generation_python_origin import encoded, function_graph, module_graph


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


compiler = Path('/opt/homebrew/opt/llvm@22/bin/clang')
native = PRODUCER / 'native/python'
files = [native / 'InputJournal.c', native / 'InputJournal.h', BASE / 'writer-interop.c']
before = {str(path): digest(path) for path in files}
binary = BASE / 'writer-interop'
command = [str(compiler), '-std=c11', '-Wall', '-Wextra', '-Werror', '-O0', '-g', '-pthread',
           '-I' + str(native), str(native / 'InputJournal.c'), str(BASE / 'writer-interop.c'), '-o', str(binary)]
build = subprocess.run(command, capture_output=True, timeout=60)
(BASE / 'writer-build.stdout').write_bytes(build.stdout)
(BASE / 'writer-build.stderr').write_bytes(build.stderr)
assert build.returncode == 0, build.stderr.decode()
result = {'consumer_head': 'd4c663d0f6f86579dfa3ed3b326664db7406439e',
          'producer_head': 'de188e5522854ca3c6ae8f7507c348c9fe3c592d',
          'scope': 'native-writer synthetic-relation interoperability only',
          'authentic_origin_qualification': False, 'application_launches': 0, 'sdk_launches': 0,
          'compiler': {'path': str(compiler), 'sha256': digest(compiler)},
          'command': command, 'build_exit': build.returncode, 'source_inputs': before,
          'writer_binary_sha256': digest(binary), 'runs': []}
for mode in ('plain-entry', 'plain-loader', 'on-entry', 'on-loader'):
    root = BASE / ('writer-' + mode)
    root.mkdir()
    source = root / 'entry.py'
    source.write_bytes(b'synthetic\0source bytes; not compiled or executed\xff\n')
    modules, selected = module_graph(), function_graph()
    for graph in (modules, selected):
        graph['nodes'][2]['value'] = str(source)
    module_file, selected_file = root / 'root.json', root / 'selected.json'
    module_file.write_bytes(encoded(modules))
    selected_file.write_bytes(encoded(selected))
    inputs = {str(path): digest(path) for path in (source, module_file, selected_file)}
    argv = [str(binary), str(root / 'inputs.journal'), str(source), str(module_file), str(selected_file), mode]
    owner = os.getpid()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=15)
    (root / 'stdout.bin').write_bytes(stdout)
    (root / 'stderr.bin').write_bytes(stderr)
    assert process.returncode == 0 and stdout == stderr == b''
    journal = python_origin.read(root / 'inputs.journal', process.pid)
    assert journal.capture_complete
    assert journal.entry_expected == ('loader' not in mode)
    assert len(journal.records) == (5 if mode.startswith('on-') else 3)
    assert journal.records[0].content == source.read_bytes()
    assert journal.records[1].input_sequence == 1 and journal.records[2].edges == (0,)
    assert journal.records[0].inode == source.stat().st_ino
    assert {str(path): digest(path) for path in (source, module_file, selected_file)} == inputs
    raw = {path.name: digest(path) for path in root.iterdir() if path.is_file()}
    result['runs'].append({'mode': mode, 'owner_pid': owner, 'writer_pid': process.pid,
                           'argv': argv, 'exit_code': process.returncode,
                           'records': len(journal.records), 'capture_complete': journal.capture_complete,
                           'comparison_steps': journal.comparison_steps, 'inputs': inputs, 'raw_sha256': raw})
assert {str(path): digest(path) for path in files} == before
result['source_preserved'] = True
result['native_writer_processes'] = len(result['runs'])
(BASE / 'writer-interop.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'native_writer_processes': len(result['runs']), 'source_preserved': True,
                  'authentic_origin_qualification': False}))
