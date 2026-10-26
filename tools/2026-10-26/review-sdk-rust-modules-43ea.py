"""Independently review original Rust module discovery without building targets."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile

ROOT = Path('/Users/sclarke/github/oteleq-qualification')
SDK = ROOT.with_name('otelc-qualification')
OUT = ROOT / '2026-10-26/sdk-rust-modules-43ea-review'
SOURCE = SDK / '2026-10-26/rust-module-root-identity/source/source.json'
HEAD = '43ea23604b8531c79d2ae6626bcf8d7f3bca3222'
ZIP_SHA = 'ee49ce9f13420b498454e020e954af8373a41fe057860efca42ded8278e7a3cd'
RUNNER = '/home/runner/work/otelc/otelc/build/rust-discovery/'


def digest(path: Path) -> str:
    """Hash retained bytes without executing any retained product."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def literal_check(version: str, source: Path) -> dict:
    """Run only the eight maintained record-reader methods on one interpreter."""
    python = ROOT / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                   'PYTHONPATH': f'{source}:{source}/tests'}
    data = OUT / f'{version}.coverage'
    argv = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--source=otelc.rust_modules', '-m', 'unittest', 'test_rust_modules', '-v']
    result = subprocess.run(argv, cwd=source, env=environment, capture_output=True, timeout=60)
    (OUT / f'{version}.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0 and b'Ran 8 tests' in result.stderr, result.stderr[-2000:]
    coverage = OUT / f'{version}-coverage.json'
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}',
                    '-o', str(coverage)], cwd=source, env=environment, capture_output=True,
                   check=True, timeout=30)
    measured = json.loads(coverage.read_text())['totals']
    assert measured['percent_covered'] == 100
    return {'python': version, 'methods': 8, 'argv': argv, 'exit': 0, 'coverage': measured}


def original_archive(source: Path) -> dict:
    """Bind original compiler statements to exact requests and physical input bytes."""
    hosted = SDK / '2026-10-26/rust-module-root-identity/hosted'
    archive = hosted / 'discovery-original.zip'
    artifact = json.loads((OUT / 'original-artifact.json').read_text())
    job = json.loads((OUT / 'original-job.json').read_text())
    assert artifact['id'] == 12630943661 and artifact['digest'] == 'sha256:' + ZIP_SHA
    assert artifact['workflow_run']['head_sha'] == HEAD and artifact['workflow_run']['id'] == 40278275115
    assert job['id'] == 121425648178 and job['run_id'] == 40278275115 and job['head_sha'] == HEAD
    assert job['conclusion'] == 'success' and digest(archive) == ZIP_SHA
    module = ast.parse((source / 'ci/rust_module_cases.py').read_text())
    fixture = next(ast.literal_eval(node.value) for node in module.body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FILES'
                                                          for t in node.targets))
    successful, refused, member_count = [], [], 0
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        assert len({info.filename for info in infos}) == len(infos)
        for info in infos:
            name = PurePosixPath(info.filename)
            assert not name.is_absolute() and '..' not in name.parts and not stat.S_ISLNK(info.external_attr >> 16)
            with bundle.open(info) as stream:
                while stream.read(1024 * 1024):
                    pass  # Reading every member to EOF checks its original ZIP CRC.
            member_count += 1
        assert bundle.read('head.txt').decode().strip() == HEAD
        tools = json.loads(bundle.read('profiles/module-discovery/compiler-inputs.json'))
        compiler = RUNNER + 'compiler/debug/otelc-rust-compiler'
        assert hashlib.sha256(bundle.read('compiler/debug/otelc-rust-compiler')).hexdigest() == tools[compiler]
        records = sorted(name for name in bundle.namelist()
                         if name.startswith('profiles/module-discovery/') and name.endswith('.result.json'))
        assert len(records) == 6
        for name in records:
            prefix = name.removesuffix('.result.json')
            folder = prefix.rsplit('/', 1)[0]
            case = folder.rsplit('/', 1)[1]
            original_root = RUNNER + folder + '/application'
            expected = {relative: text.encode() for relative, text in fixture.items()}
            if 'unicode_crlf_and_bom' in case:
                expected['main.rs'] = '\ufeffmod café { fn value() {} }\r\nfn main() {}\r\n'.encode()
            catalogue = {}
            for relative, raw in expected.items():
                assert bundle.read(folder + '/application/' + relative) == raw
                catalogue[original_root + '/' + relative] = hashlib.sha256(raw).hexdigest()
            assert json.loads(bundle.read(folder + '/original-inputs.json')) == catalogue
            request = json.loads(bundle.read(prefix + '.request.json'))
            result = json.loads(bundle.read(name))
            argv = result['arguments']
            assert argv[:6] == [compiler, original_root + '/main.rs', '--crate-name', 'module_map',
                                '--edition=2024', '--sysroot']
            assert argv[6] == '/home/runner/.rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu'
            flags = ['--cfg', 'feature="selected"'] if 'cfg_selected_missing' in case else []
            assert argv[7:] == ['-Copt-level=2', *flags, '-o', RUNNER + prefix + '.application']
            assert prefix + '.application' not in bundle.namelist()
            expected_request = {'schema_version': 1, 'mode': 'module-inspect',
                                'root': original_root, 'entry': original_root + '/main.rs',
                                'sources': catalogue, 'selected': [],
                                'output': RUNNER + prefix + '.inventory.json'}
            if 'selection_and_changed' in case:
                if prefix.endswith('command-1'):
                    expected_request['selected'] = ['main.rs::main']
                else:
                    expected_request['sources'] = catalogue | {original_root + '/main.rs': '0' * 64}
            assert request == expected_request
            if result['exit_code'] != 0:
                assert 'cfg_selected_missing' in case or 'selection_and_changed' in case
                assert prefix + '.inventory.json' not in bundle.namelist()
                refused.append(name)
                continue
            value = json.loads(bundle.read(prefix + '.inventory.json'))
            assert value['sources'] == catalogue and value['crate_name'] == 'module_map'
            assert value['schema_version'] == 1 and value['mode'] == 'module-inspect'
            assert value['kind'] == 'otelc.rust.module-inventory' and value['source_complete'] is False
            assert value['byte_coordinates'] == 'original-utf8'
            rows = {row['compiler_name']: row for row in value['modules']}
            assert len(rows) == len(value['modules']) and rows['']['parent'] is None
            for row in rows.values():
                for field in ('declaration', 'body'):
                    location = row[field]
                    raw = expected[location['file'].removeprefix(original_root + '/')]
                    assert type(location['start']) is type(location['end']) is int
                    assert 0 <= location['start'] <= location['end'] <= len(raw)
            if 'unicode_crlf_and_bom' in case:
                assert set(rows) == {'', 'café'}
                location = rows['café']['declaration']
                assert location['start'] == 3
                assert expected['main.rs'][location['start']:location['end']].decode() == 'mod café { fn value() {} }'
                assert b'\r\n' in expected['main.rs'][rows['']['body']['start']:rows['']['body']['end']]
            else:
                assert set(rows) == {'', 'outer', 'outer::inner', 'tree', 'tree::leaf', 'inline',
                                     'inline::child', 'aliased', 'expanded', 'main::block'}
                assert rows['tree::leaf']['body']['start'] == rows['tree::leaf']['body']['end'] == 0
                for route, reason in (('expanded', 'expanded'), ('main::block', 'block_module')):
                    assert rows[route]['eligible'] is False and rows[route]['reason'] == reason
            successful.append({'result': name, 'modules': len(rows), 'source_inputs': len(catalogue)})
    assert len(successful) == 3 and len(refused) == 3
    assert digest(archive) == ZIP_SHA
    return {'archive_sha256': ZIP_SHA, 'members_crc_checked': member_count,
            'compiler_invocations': 6, 'successful_inventories': successful,
            'expected_refusals': refused, 'new_local_compiler_or_application_executions': 0}


def main() -> None:
    """Save the independent review with its exact source and execution limits."""
    spec = importlib.util.spec_from_file_location('source_guard', ROOT / '2026-10-26/review-python-label-bound.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    manifest = json.loads(SOURCE.read_text())
    assert manifest['head'] == HEAD
    held = guard.check_source(manifest)
    source = Path(manifest['root'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(lambda version: literal_check(version, source), ('312', '314')))
    archive = original_archive(source)
    assert guard.check_source(manifest) == held
    result = {'status': 'clear within original module-map component scope', 'head': HEAD,
              'source_preservation': held, 'literal_checks': checks, 'original_linux_archive': archive,
              'findings': [], 'manual_review': [
                  'No weaving, selected functions or image emission in module-inspect mode.',
                  'Actual crate_name is caller-bound separately from unchanged crate-relative DefPaths.',
                  'Physical original UTF-8 intervals preserve BOM/CRLF and empty external bodies.',
                  'Expanded/block-local modules and descendants cannot gain a private caller route.',
                  'Existing public source-build profiles are unchanged; no helper injection is claimed.',
              ], 'limits': 'Focused Linux compiler component plus eight fresh literal methods per Python. No local Rust/compiler/SDK build, target launch, private-call implementation, macOS qualification, whole source/compiler closure or generated/shipping admission. Original ee focused failure remains failed.'}
    (OUT / 'review.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'source_files': held['files'],
                      'literal_methods_each_python': 8, 'original_compiler_invocations': 6,
                      'review_sha256': digest(OUT / 'review.json')}))


if __name__ == '__main__':
    main()
