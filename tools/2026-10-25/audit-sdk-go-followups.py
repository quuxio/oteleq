"""Review frozen Go corrections using original hosted SDK evidence, without builds."""

from collections import defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

BASE = Path('/Users/sclarke/github/oteleq-qualification')
SDK = Path('/Users/sclarke/github/otelc-qualification/2026-10-25')
OUTPUT = BASE / '2026-10-25/sdk-go-followups-review'
PYTHON = BASE / '2026-10-24/python-live-metrics/env-312/bin/python'
WRAPPER = BASE / '2026-10-20/pause-for-reboot/quux-oteleq-gh.py'
TARGETS = ('go-lifetime-observer-cleanup', 'go-control-export-cancellation', 'go-fixture-checksums')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def frozen(manifest: dict) -> None:
    root = Path(manifest['root'])
    names = subprocess.check_output(['git', 'ls-files', '-c', '-o', '--exclude-standard', '-z'], cwd=root)
    assert set(names.decode().rstrip('\0').split('\0')) == set(manifest['source_facts'])
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip() == manifest['head']
    for name, expected in manifest['source_facts'].items():
        path = root / name
        info = path.lstat()
        assert [digest(path), info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns] == expected, name
        assert [info.st_uid, info.st_gid, info.st_nlink] == manifest['extra_facts'][name], name
    assert digest(Path(manifest['archive'])) == manifest['archive_sha256']


def api(endpoint: str, name: str) -> bytes:
    environment = dict(os.environ, XDG_CACHE_HOME=str(BASE / 'work/gh-cache'))
    result = subprocess.run([str(PYTHON), str(WRAPPER), 'api', endpoint],
                            env=environment, capture_output=True, timeout=90)
    result.check_returncode()
    (OUTPUT / name).write_bytes(result.stdout)
    return result.stdout


def original_capture(archive: Path, metadata: dict, head: str, root: Path) -> dict:
    assert digest(archive) == metadata['digest'].removeprefix('sha256:')
    assert archive.stat().st_size == metadata['size_in_bytes']
    assert metadata['workflow_run']['head_sha'] == head
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert len(names) == len(set(names)) == 7
        assert bundle.read('go-foundation/head.txt').decode().strip() == head
        log = bundle.read('go-foundation/go-tests.log').decode()
        assert 'go vet -mod=readonly ./...' in log
        assert 'go test -mod=readonly -race -count=1 -coverprofile=' in log
        packages = [line for line in log.splitlines() if line.startswith('ok')]
        assert len(packages) == 4 and not any(line.startswith('FAIL') for line in log.splitlines())
        coverage = bundle.read('go-coverage.out').decode().splitlines()
        assert coverage[0] == 'mode: atomic'
        totals, covered = defaultdict(int), defaultdict(int)
        for line in coverage[1:]:
            block, statements, hits = line.split()
            name = block.split(':', 1)[0]
            totals[name] += int(statements)
            covered[name] += int(statements) * (int(hits) > 0)
        expected = {'io.quux.otelc/go/' + path.relative_to(root / 'adapters/go').as_posix()
                    for path in (root / 'adapters/go').glob('*/*.go') if not path.name.endswith('_test.go')}
        assert set(totals) == expected and len(totals) == 16
        percentages = {name: 100 * covered[name] / total for name, total in totals.items()}
        assert all(value >= 80 for value in percentages.values())
        converted = bundle.read('go-sonar-coverage.out').decode()
        assert converted == '\n'.join(coverage).replace('io.quux.otelc/go/', 'adapters/go/') + '\n'
        python = json.loads(bundle.read('go-foundation/python-coverage.json'))
        python_percentages = {name: row['summary']['percent_covered'] for name, row in python['files'].items()}
        assert len(python_percentages) == 4 and all(value >= 80 for value in python_percentages.values())
        assert b'\nOK\n' in bundle.read('go-foundation/python-tests.log')
    return {'head': head, 'artifact_id': metadata['id'], 'archive': str(archive),
            'archive_sha256': digest(archive), 'sdk_packages_passed_with_race': 4,
            'go_component_percentages': percentages, 'python_component_percentages': python_percentages}


def main() -> None:
    manifests = {name: json.loads((SDK / name / 'source.json').read_text()) for name in TARGETS}
    for manifest in manifests.values():
        frozen(manifest)
    final = manifests['go-fixture-checksums']
    root = Path(final['root'])
    for name, prefix in (('go-lifetime-observer-cleanup', 'adapters/go/probe/'),
                         ('go-control-export-cancellation', 'adapters/go/')):
        earlier = manifests[name]
        for filename, facts in earlier['source_facts'].items():
            if filename.startswith(prefix):
                assert final['source_facts'][filename][0] == facts[0], filename
    captures = []
    for target in ('go-lifetime-observer-cleanup', 'go-fixture-checksums'):
        manifest = manifests[target]
        hosted = SDK / target / 'hosted'
        for host in ('linux', 'macos'):
            suffix = '-original-audit.json' if target == 'go-lifetime-observer-cleanup' else '-audit.json'
            receipt = json.loads((hosted / (host + suffix)).read_text())
            artifact = receipt['artifact']
            live = json.loads(api(f'repos/quuxio/otelc/actions/artifacts/{artifact["id"]}',
                                  target + '-' + host + '-artifact.json'))
            assert live['digest'] == artifact['digest'] and not live['expired']
            job = json.loads(api(f'repos/quuxio/otelc/actions/jobs/{receipt["job"]}',
                                 target + '-' + host + '-job.json'))
            assert (job['status'], job['conclusion'], job['head_sha']) == ('completed', 'success', manifest['head'])
            archive = hosted / (host + ('-original-artifact.zip' if target == 'go-lifetime-observer-cleanup' else '-original.zip'))
            row = original_capture(archive, live, manifest['head'], Path(manifest['root']))
            raw_log = gzip.decompress((hosted / (host + '-original.log.gz')).read_bytes())
            assert hashlib.sha256(raw_log).hexdigest() == receipt['original_log_sha256']
            if target == 'go-fixture-checksums':
                assert raw_log.count(b'all modules verified') == 2
                step, = [step for step in job['steps'] if step['name'] == 'Verify retained fixture dependency checksums']
                assert (step['status'], step['conclusion']) == ('completed', 'success')
            captures.append(row)
            print(target, host, 'original SDK/race and16Go/4Python floors pass', flush=True)
    for job_id in (121289783217, 121289782932):
        job = json.loads(api(f'repos/quuxio/otelc/actions/jobs/{job_id}', 'cancellation-' + str(job_id) + '-job.json'))
        assert (job['status'], job['conclusion'], job['head_sha']) == ('completed', 'success', manifests['go-control-export-cancellation']['head'])
    node = '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
    cli = BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'
    result = subprocess.run([node, str(cli), '--config', '.markdownlint.json', 'docs/go-source.md',
                             'docs/go-sdk-controls.md'], cwd=root, capture_output=True, timeout=60)
    (OUTPUT / 'markdown.stderr').write_bytes(result.stderr)
    result.check_returncode()
    for manifest in manifests.values():
        result = subprocess.run(['git', 'diff', '--check', manifest['base'], 'HEAD'],
                                cwd=manifest['root'], capture_output=True, timeout=30)
        result.check_returncode()
        frozen(manifest)
    sumdb = json.loads((OUTPUT / 'sumdb/review.json').read_text())
    assert sumdb['unique_modules'] == 16 and sumdb['entries_per_fixture'] == 32
    result = {'status': 'clear for the three narrow Go source corrections',
              'heads': {name: manifest['head'] for name, manifest in manifests.items()},
              'source_files_held': {name: len(manifest['source_facts']) for name, manifest in manifests.items()},
              'hosted_captures': captures, 'cancellation_original_jobs_verified': [121289783217, 121289782932],
              'inherited_source_binding': 'Exact final0955 source/test bytes for the5792probe andcc395SDK/runtime are preserved.',
              'official_checksum_lookups': str(OUTPUT / 'sumdb/review.json'),
              'local_sdk_compiler_native_application_builds': 0,
              'limits': 'Source review plus independent original hosted evidence audit. No local Go compilation or replay. Cancellation raw captures are the descendant0955 runs with byte-identical SDK/test inputs; its own original jobs are separately verified terminal success. This does not admit broader public Go/oteleq integration.'}
    path = OUTPUT / 'review.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print('review', path, 'sha256', digest(path))


if __name__ == '__main__':
    main()
