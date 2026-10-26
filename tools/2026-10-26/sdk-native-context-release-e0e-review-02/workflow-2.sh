python3 -c 'import shutil; assert shutil.disk_usage(".").free >= 8 * 1024**3, "at least 8 GiB required"'
before_root="$GITHUB_WORKSPACE/build/native-context-before/source"
mkdir -p "$before_root"
git archive --format=tar --output build/native-context/before-source.tar 98b3cfedd685170cfa71e71b2a7e6f10ad40c416
tar -xf build/native-context/before-source.tar -C "$before_root"
cp adapters/native/tests/function_runtime_test.cpp "$before_root/adapters/native/tests/function_runtime_test.cpp"
set +e
(cd "$before_root" && OTELC_CPP_ANALYSIS=1 PYTHONDONTWRITEBYTECODE=1 "$GITHUB_WORKSPACE/.venv/bin/python" -m ci.check_native_controls) 2>&1 | tee build/native-context/before-tests.log
before_exit=${PIPESTATUS[0]}
set -e
OTELC_BEFORE_EXIT="$before_exit" .venv/bin/python - <<'PY'
import hashlib, json, os, re
from pathlib import Path
output = Path('build/native-context')
root = Path('build/native-context-before/source')
assert int(os.environ['OTELC_BEFORE_EXIT']) == 1
assert hashlib.sha256((output / 'before-source.tar').read_bytes()).hexdigest() == '91a88cd3db02ef579bcf0a367316331d86525e7a6dbd55519e08bc93c9f09fc8'
text = (output / 'before-tests.log').read_text()
assert re.search(r'\bnative_function_runtime\s+\(Timeout\)', text)
logs = list((root / 'build').glob('native-controls-*/Testing/Temporary/LastTest.log'))
assert len(logs) == 1
ctest = logs[0].read_text()
assert ctest.count('Test Passed.') == 2
assert ctest.count('native owned context: final-reference deleter entered') == 1
assert 'native owned context: 6 SDK groups passed' not in ctest
(output / 'before-ctest.log').write_bytes(logs[0].read_bytes())
database = logs[0].parents[2] / 'compile_commands.json'
(output / 'before-compile-commands.json').write_bytes(database.read_bytes())
test = Path('adapters/native/tests/function_runtime_test.cpp')
assert (root / test).read_bytes() == test.read_bytes()
(output / 'before-result.json').write_text(json.dumps({
    'runtime_head': '98b3cfedd685170cfa71e71b2a7e6f10ad40c416',
    'native_runtime_sha256': hashlib.sha256((root / 'adapters/native/src/function_runtime.cpp').read_bytes()).hexdigest(),
    'regression_test_sha256': hashlib.sha256(test.read_bytes()).hexdigest(),
    'exit_code': 1, 'ctest_passed': 2,
    'expected_failure': 'native_function_runtime Timeout after the actual final-reference deleter entered',
    'scope': 'Old runtime with the maintained new regression test only; not a passing SDK/provider qualification.'}, indent=2) + '\n')
PY
