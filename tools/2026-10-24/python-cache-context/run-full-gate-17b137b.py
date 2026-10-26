"""Run the complete gate on the frozen integration, then recheck every tracked file."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-cache-context')
ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-cache-context')
FOLDER = ROOT / 'full-gate-17b137b'
assert FOLDER.is_dir()
EXPECTED = json.loads((ROOT / 'source-17b137b.json').read_bytes())
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip() == EXPECTED['head']
assert all((REPO / name).is_file() and hashlib.sha256((REPO / name).read_bytes()).hexdigest() == digest for name, digest in EXPECTED['files'].items())
PYTHON = '/Users/sclarke/github/oteleq-qualification/2026-10-22/node-source-consumer-0f05020/validation-hash-env/bin/python'
NODE = '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
RUST = '/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin'
GO = '/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
LLVM = '/opt/homebrew/opt/llvm@22/bin'
JDK = '/opt/homebrew/opt/openjdk@21'
environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'RUSTUP_TOOLCHAIN': '1.98.1-aarch64-apple-darwin',
    'CARGO_TARGET_DIR': str(FOLDER / 'target'),
    'OTELC_CLANG': LLVM + '/clang', 'OTELC_CLANGXX': LLVM + '/clang++', 'LLVM_SYMBOLIZER_PATH': LLVM + '/llvm-symbolizer',
    'OTELC_JAVA': JDK + '/bin/java', 'OTELC_JAVAC': JDK + '/bin/javac', 'JAVA_HOME': JDK,
    'OTELC_GO': GO, 'OTELC_NODE': NODE, 'GOTOOLCHAIN': 'local',
    'LLVM_COV': RUST + '/lib/rustlib/aarch64-apple-darwin/bin/llvm-cov',
    'LLVM_PROFDATA': RUST + '/lib/rustlib/aarch64-apple-darwin/bin/llvm-profdata'}
environment['PATH'] = ':'.join((RUST + '/bin', LLVM, JDK + '/bin', str(Path(NODE).parent), str(Path(GO).parent), environment['PATH']))
command = ['make', 'check', 'PYTHON=' + PYTHON, 'NODE=' + NODE]
(FOLDER / 'command.json').write_text(json.dumps({'argv': command, 'cwd': str(REPO),
    'head': EXPECTED['head'], 'selected_tools': {key: environment[key] for key in
    ('OTELC_CLANG', 'OTELC_CLANGXX', 'OTELC_JAVA', 'OTELC_JAVAC', 'OTELC_GO', 'OTELC_NODE', 'LLVM_COV', 'LLVM_PROFDATA')}}, indent=2) + '\n')
started = time.monotonic()
with (FOLDER / 'make-check.log').open('xb') as log:
    result = subprocess.run(command, cwd=REPO, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
changed = [name for name, digest in EXPECTED['files'].items()
           if not (REPO / name).is_file() or hashlib.sha256((REPO / name).read_bytes()).hexdigest() != digest]
proof = {'head': EXPECTED['head'], 'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 3),
    'source_preserved': not changed, 'tracked_files_checked': len(EXPECTED['files']), 'changed': changed}
(FOLDER / 'result.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof), flush=True)
assert not changed, changed
sys.exit(result.returncode)
