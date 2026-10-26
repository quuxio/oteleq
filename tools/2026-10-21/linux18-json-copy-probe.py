import json
from pathlib import Path
import subprocess

out = Path('/output')
compiler = '/usr/bin/clang++-18'
build = subprocess.run([compiler, '-std=c++17', '-g', '-fno-exceptions', '-I/usr/lib/llvm-18/include',
    '/probe.cpp', '/usr/lib/llvm-18/lib/libLLVM.so', '-o', out/'json-copy'], capture_output=True, check=True)
ast = subprocess.run([compiler, '-std=c++17', '-Xclang', '-ast-dump=json', '-fsyntax-only',
    out/'crash-project/app.cpp'], capture_output=True, check=True)
(out/'plain-ast.json').write_bytes(ast.stdout)
result = subprocess.run([out/'json-copy', out/'plain-ast.json'], capture_output=True, check=False)
(out/'copy.stdout').write_bytes(result.stdout)
(out/'copy.stderr').write_bytes(result.stderr)
print('plain LLVM JSON parse/copy:', result.returncode)
if not result.returncode:
    assert json.loads(ast.stdout) == json.loads(result.stdout)
    print('copy preserved the original Clang AST')
raise SystemExit(result.returncode)
