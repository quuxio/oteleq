"""Review the exact normal Go/main integration without starting a compiler."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path('/Users/sclarke/github/oteleq-qualification')
SOURCE = Path('/Users/sclarke/github/otelc-qualification/work/go-current-main-integration')
OUT = ROOT / '2026-10-26/sdk-go-main-c475-review'
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/go-current-main-integration/source.json')
HEAD = 'c4752afd6484b42dfbc571eb114c77d1da53909f'
PARENTS = ('8877ab83c299b508fd1735220f9381c49dd81056', '5318934ef8c16d5570a25366aa31e63e0f191b34')
MODULES = ('test_go_scope_patch', 'test_go_health', 'test_go_telemetry_bundle',
           'test_go_context_bundle', 'test_go_upstream_builder', 'test_go_runtime_config')


def git(*args: str) -> bytes:
    """Read the original integration's Git objects."""
    return subprocess.check_output(['git', *args], cwd=SOURCE)


def tree(ref: str) -> dict[str, str]:
    """Retain the complete tracked path/blob denominator of a revision."""
    result = {}
    for row in git('ls-tree', '-r', '-z', ref).split(b'\0'):
        if row:
            metadata, name = row.split(b'\t', 1)
            result[name.decode()] = metadata.decode()
    return result


def bounded_tests(version: str) -> dict:
    """Exercise six maintained Python components with their fixed fake tools."""
    python = ROOT / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': f'{SOURCE}:{SOURCE}/tests'}
    args = [str(python), '-B', '-m', 'unittest', *MODULES, '-v']
    result = subprocess.run(args, cwd=SOURCE, env=env, capture_output=True, text=True, timeout=120)
    (OUT / f'python-{version}.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr[-5000:]
    assert 'Ran 30 tests' in result.stderr and '\nOK\n' in result.stderr
    return {'python': version, 'argv': args, 'methods': 30, 'exit_code': result.returncode}


def main() -> None:
    """Freeze the source proof, exact conflict resolution and bounded results."""
    OUT.mkdir(exist_ok=False)
    spec = importlib.util.spec_from_file_location('original_source_guard', ROOT / '2026-10-26/review-python-label-bound.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['head'] == HEAD and manifest['base'] == PARENTS[0]
    before = guard.check_source(manifest)
    assert git('show', '-s', '--format=%H %P', HEAD).decode().split() == [HEAD, *PARENTS]
    assert git('status', '--porcelain') == b''
    final, first, second = (tree(ref) for ref in (HEAD, *PARENTS))
    assert set(final) == set(first) | set(second)
    manual = [name for name, value in final.items() if value not in (first.get(name), second.get(name))]
    assert set(manual) == {'Makefile', 'README.md'}
    go = [name for name in final if name.startswith(('adapters/go/', 'otelc/go_', 'tests/test_go', 'ci/go_', 'ci/build_go'))
          or name == '.github/workflows/go-foundation.yml']
    assert all(final[name] == first.get(name) for name in go)
    assert final['.github/workflows/ci.yml'] == second['.github/workflows/ci.yml']
    ancestor = git('merge-base', *PARENTS).decode().strip()
    with tempfile.TemporaryDirectory() as temporary:
        for name in manual:
            paths = []
            for role, ref in (('go', PARENTS[0]), ('ancestor', ancestor), ('main', PARENTS[1])):
                path = Path(temporary) / (role + '-' + name)
                path.write_bytes(git('show', ref + ':' + name))
                paths.append(str(path))
            merged = subprocess.run(['git', 'merge-file', '--stdout', '--diff3', '-L', 'go', '-L', 'ancestor', '-L', 'main', *paths],
                                    capture_output=True, text=True)
            expected = merged.stdout
            if name == 'Makefile':
                pattern = r'^<<<<<<< go\n(.*?)^\|\|\|\|\|\|\| ancestor\n(.*?)^=======\n(.*?)^>>>>>>> main\n'
                chunks = list(re.finditer(pattern, expected, re.M | re.S))
                assert merged.returncode == 1 and len(chunks) == 1
                chunk = chunks[0]
                ours, base, theirs = chunk.groups()
                lines = ours.splitlines(keepends=True)
                assert len(lines) == 2 and lines[1] == base
                assert "'go-upstream Build the pinned original-source Go compiler wrapper; --scope-safe is a separate private profile'" in lines[0]
                assert theirs.replace(" 'native-benchmark-check Check C/C++ stock/four-state timings, accounting and 80% coverage'", '') == base
                expected = expected[:chunk.start()] + lines[0] + theirs + expected[chunk.end():]
            else:
                assert merged.returncode == 0
            assert git('show', HEAD + ':' + name).decode() == expected, name
            (OUT / (name + '.merge-review')).write_text(expected)
    subprocess.run(['git', 'diff', '--check', *PARENTS[:1], HEAD], cwd=SOURCE, check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tests = list(pool.map(bounded_tests, ('312', '314')))
    after = guard.check_source(manifest)
    assert before == after
    prior = ROOT / '2026-10-25/sdk-go-test-clarity-review/review.json'
    assert hashlib.sha256(prior.read_bytes()).hexdigest() == 'cbab838d65f12cdd98fa22094606244f46457ac0e7284d04174f9f7a3e21b5bb'
    record = {'status': 'clear for exact normal main integration', 'head': HEAD, 'parents': PARENTS,
              'source_preservation': after, 'all_paths_from_a_parent_except': manual,
              'go_files_exact_first_parent': len(go), 'ci_exact_main_parent': True,
              'manual_resolution': 'The ordinary three-way README result is exact; the only Makefile conflict retains the one original Go helper line plus the current main help line. All other merged bytes match the ordinary three-way result.',
              'tests': tests, 'findings': [], 'prior_test_extraction_review_sha256': hashlib.sha256(prior.read_bytes()).hexdigest(),
              'local_compiler_builds': 0, 'local_sdk_builds': 0, 'local_application_launches': 0,
              'limits': 'Narrow normal-integration review, combined with the separate original test-extraction review. This does not clear the entire Go foundation or new public runtime capabilities. Current-head hosted required checks and accepted analysis findings remain separate.'}
    (OUT / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
