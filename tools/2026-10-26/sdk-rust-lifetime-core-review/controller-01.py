"""Review frozen Rust lifetime core sources, literal controls and hosted records."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile


BASE = Path('/Users/sclarke/github/oteleq-qualification')
SDK = Path('/Users/sclarke/github/otelc-qualification')
SOURCE = SDK / 'work/rust-public-suite-budget'
OUT = BASE / '2026-10-26/sdk-rust-lifetime-core-review'
OUT.mkdir(mode=0o700)
spec = importlib.util.spec_from_file_location('source_guard', BASE / '2026-10-26/review-python-label-bound.py')
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
manifests = {
    name: json.loads((SDK / f'2026-10-25/{name}/source.json').read_text())
    for name in ('rust-mir-erased-regions', 'rust-types-suite-budget', 'rust-public-suite-budget')
}
held_before = {name: guard.check_source(value) for name, value in manifests.items()}
core = [f'native/rust/compiler/src/{name}.rs' for name in ('drops', 'hooks', 'lifetimes', 'request')]
for name in core:
    expected = (SOURCE / name).read_bytes()
    for manifest in manifests.values():
        actual = subprocess.check_output(['git', 'show', manifest['head'] + ':' + name], cwd=SOURCE)
        assert actual == expected, (name, manifest['head'])


def api(endpoint: str) -> dict:
    """Verify quuxio for each independent hosted-evidence lookup."""
    result = subprocess.run(
        [str(BASE / '2026-10-24/python-live-metrics/env-312/bin/python'),
         str(BASE / '2026-10-20/pause-for-reboot/quux-oteleq-gh.py'), 'api', endpoint],
        env=dict(os.environ, XDG_CACHE_HOME=str(BASE / 'work/gh-cache')),
        capture_output=True, check=True, timeout=60,
    )
    return json.loads(result.stdout)


def local_controls(version: str) -> dict:
    """Run only the named non-building unit classes on the frozen final root."""
    modules = ['test_rust_lifetimes', 'test_rust_public.RustInputTests',
               'test_rust_public.RustBoundaryTests',
               'test_rust_public_lifetimes.RustLifetimeProfileTests',
               'test_rust_benchmark.RustBenchmarkContractTests',
               'test_rust_compiler.RustToolRecordTests',
               'test_rust_compiler.RustCompilerCommandTests']
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                       PYTHONPATH=f'{SOURCE}:{SOURCE}/tests')
    data = OUT / f'{version}.coverage'
    argv = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--source=otelc.rust_lifetimes', '-m', 'unittest', *modules, '-v']
    result = subprocess.run(argv, cwd=SOURCE, env=environment,
                            capture_output=True, text=True, timeout=120)
    (OUT / f'{version}-controls.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr[-5000:]
    count = re.search(r'Ran (\d+) tests', result.stderr)
    assert count is not None and int(count[1]) > 50 and 'skipped=' not in result.stderr
    destination = OUT / f'{version}-coverage.json'
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json',
                    f'--data-file={data}', '-o', str(destination)],
                   cwd=SOURCE, env=environment, capture_output=True, check=True, timeout=30)
    coverage = json.loads(destination.read_text())['totals']
    assert coverage['percent_covered'] >= 80
    return {'python': version, 'methods': int(count[1]), 'exit_code': 0,
            'argv': argv, 'lifetime_reader_statement_coverage': coverage}


def hosted(platform: str, artifact_id: int, job_id: int) -> dict:
    """Recheck native coverage and all genuine automatic-drop final checkpoints."""
    directory = SDK / '2026-10-26/rust-types-suite-budget/hosted'
    archive = directory / f'sdk-{platform}-original.zip'
    artifact = api(f'repos/quuxio/otelc/actions/artifacts/{artifact_id}')
    job = api(f'repos/quuxio/otelc/actions/jobs/{job_id}')
    expected_head = manifests['rust-types-suite-budget']['head']
    assert artifact['workflow_run']['head_sha'] == expected_head
    assert job['head_sha'] == expected_head and job['conclusion'] == 'success'
    assert archive.stat().st_size == artifact['size_in_bytes']
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert artifact['digest'] == 'sha256:' + digest
    (OUT / f'{platform}-github.json').write_text(json.dumps({'artifact': artifact, 'job': job}, indent=2) + '\n')
    wanted = core + ['native/rust/compiler/src/main.rs',
                     'native/rust/compiler/src/instrument.rs', 'native/rust/bridge/src/lib.rs']
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert len(names) == len(set(names))
        exported = {}
        for suffix in ('compiler-coverage.stdout', 'bridge-coverage.stdout'):
            name, = [name for name in names if name.endswith(suffix)]
            value = json.loads(bundle.read(name))
            assert value['type'] == 'llvm.coverage.json.export'
            for document in value['data']:
                for file in document['files']:
                    exported[file['filename']] = file['summary']['lines']
        physical = {}
        filename = None
        for line in bundle.read('rust-coverage.lcov').decode().splitlines():
            if line.startswith('SF:'):
                filename = line[3:]
                physical.setdefault(filename, {})
            elif line.startswith('DA:'):
                number, count = map(int, line[3:].split(',')[:2])
                assert number > 0 and count >= 0 and filename is not None
                rows = physical[filename]
                rows[number] = max(rows.get(number, 0), count)
        coverage = {}
        for relative in wanted:
            file, = [name for name in exported if name.endswith('/' + relative)]
            summary = exported[file]
            rows = physical[file]
            covered = sum(count > 0 for count in rows.values())
            assert summary['count'] > 0 and summary['covered'] / summary['count'] >= 0.8
            assert rows and covered / len(rows) >= 0.8
            coverage[relative] = {'llvm_export_lines': summary,
                                  'physical_DA_count': len(rows), 'physical_DA_covered': covered}
        healths = [name for name in names if name.endswith('/health.json')]
        automatic = [name for name in healths if '/automatic-drop-' in name]
        assert len(healths) == 24 and len(automatic) == 8
        for name in automatic:
            value = json.loads(bundle.read(name))
            assert value['schema_version'] == 5 and value['language'] == 'rust'
            assert value['lifecycle'] == {'flush': 'succeeded', 'shutdown': 'succeeded'}
            assert value['drop_accounting'] == dict(types='2', admitted='12', completed='12',
                live='0', dropping='0', ending='0', censored='0', lost='0', duplicates='0', invalid='0',
                closing=True, closed=True)
            assert value['function_accounting']['started'] == value['function_accounting']['ended'] == '4'
            assert value['function_accounting']['active'] == value['function_accounting']['lost'] == '0'
            result = json.loads(bundle.read(name.removesuffix('health.json') + 'process-result.json'))
            assert result == {'exit_code': 0}
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
    return {'platform': platform, 'head': expected_head, 'job': job_id,
            'archive_sha256': digest, 'health_records': len(healths),
            'automatic_drop_checkpoints': len(automatic), 'coverage': coverage,
            'limits': 'Hosted checkpoint/coverage evidence; original HTTP bodies and rebuilt binaries are not in this small artifact.'}


with ThreadPoolExecutor(max_workers=4) as pool:
    jobs = [pool.submit(local_controls, version) for version in ('312', '314')]
    jobs += [pool.submit(hosted, *args) for args in (
        ('linux', 12618965718, 121325377324), ('macos', 12618703475, 121325377154))]
    results = [job.result() for job in jobs]
held_after = {name: guard.check_source(value) for name, value in manifests.items()}
assert held_before == held_after
record = {
    'status': 'clear for the reviewed runtime-MIR insertion and complete lifetime-snapshot binding core',
    'reviewed_files': core, 'reviewed_core_head': manifests['rust-mir-erased-regions']['head'],
    'byte_identical_core_descendants': [manifests[name]['head'] for name in ('rust-types-suite-budget', 'rust-public-suite-budget')],
    'source_preservation': held_after, 'local_controls': results[:2], 'hosted': results[2:],
    'findings': [], 'manual_review': [
        'Original runtime MIR is cloned after drop elaboration and its complete discovery body fingerprint is recomputed before insertion.',
        'Only concrete original root-local ADTs needing Drop are accepted; argument/return, escape/copy, projected-drop and factory-call shapes refuse visibly.',
        'Successful constructors precede observation; accepted whole-local moves transfer keys without duplicating construction. Original drop flags, normal successors and cleanup unwind edges remain in place.',
        'A normal drop during an outer panic uses the normal completion hook; only the actual drop unwind edge marks an exceptional drop. Hooks use typed ABI checks and erased runtime string-reference regions.',
    ],
    'new_sdk_builds': 0, 'new_compiler_builds': 0,
    'limits': 'Bounded core source review and corroborating component checkpoints/coverage only. The complete public build/launch API, original wire receipts, oteleq consumer lifetime integration, arbitrary ownership/Cargo/async support, performance and shipping qualification remain separate. No old GitHub gate result is transferred to a new head.',
}
(OUT / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'status': record['status'], 'methods_per_python': [r['methods'] for r in results[:2]],
                  'held': held_after, 'hosted_platforms': [r['platform'] for r in results[2:]]}, indent=2))
