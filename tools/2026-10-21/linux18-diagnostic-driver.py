"""Retain a frozen Linux compiler helper and symbolise its actual crash frames."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

OUTPUT = Path('/output')
spec = importlib.util.spec_from_file_location('frontend_tests', '/source/tests/test_generation_native_frontend.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_execute = module.execute
original_build = module.native_frontend.build


def retained_build(compiler, destination, source_root, execute):
    result = original_build(compiler, destination, source_root, execute)
    shutil.copytree(destination, OUTPUT / 'helper')
    return result


def diagnostic_execute(command, directory):
    result = original_execute(command, directory)
    if result.returncode < 0:
        sys.stderr.buffer.write(result.stderr)
        (OUTPUT / 'crash.stderr').write_bytes(result.stderr)
        (OUTPUT / 'crash.stdout').write_bytes(result.stdout)
        (OUTPUT / 'crash-command.json').write_text(json.dumps(list(map(str, command))))
        shutil.copytree(directory, OUTPUT / 'crash-project')
        offsets = re.findall(rb'native-discover\+0x([0-9a-f]+)', result.stderr)
        if offsets:
            symbols = subprocess.run(['/usr/lib/llvm-18/bin/llvm-symbolizer', '--obj=' + str(command[0])],
                input=b''.join(b'0x' + value + b'\n' for value in offsets), capture_output=True, check=False, timeout=30)
            sys.stderr.buffer.write(symbols.stdout)
            (OUTPUT / 'crash-symbols.txt').write_bytes(symbols.stdout)
    return result


module.native_frontend.build = retained_build
module.execute = diagnostic_execute
suite = unittest.defaultTestLoader.loadTestsFromModule(module)
result = unittest.TextTestRunner(verbosity=2).run(suite)
(OUTPUT / 'result.json').write_text(json.dumps({'tests': result.testsRun, 'errors': len(result.errors),
    'failures': len(result.failures), 'success': result.wasSuccessful()}) + '\n')
raise SystemExit(0 if result.wasSuccessful() else 1)
