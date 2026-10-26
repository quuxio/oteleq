"""Run unchanged native byte auditors with one disposable selected working set."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import qualification_archive_selection as selection
import qualification_temporary_selection as temporary

BASE = Path('/Users/sclarke/github/oteleq-qualification')
SPECS = {
    'metric': ('audit-native-metric-captures-06.py',
               '2026-10-25/native-metric-controls/source-5ff52e0.json'),
    'lifetime': ('audit-native-lifetime-shard-02.py',
                 '2026-10-25/native-lifetime-build/source-d1b1a0e.json'),
}


def source_guard(manifest: dict) -> dict:
    """Recheck every original source fact, without repairing an old snapshot."""
    for name, expected in manifest['source_facts'].items():
        path = Path(manifest['root']) / name
        digest = selection.sha256(path)
        row = path.lstat()
        observed = [digest, row.st_dev, row.st_ino, row.st_mode, row.st_size,
                    row.st_mtime_ns, row.st_ctime_ns, row.st_uid, row.st_gid, row.st_nlink]
        assert len(expected) in (7, 10) and observed[:len(expected)] == expected, name
        assert observed[7:] == manifest['extra_facts'][name], name
    assert selection.sha256(Path(manifest['archive'])) == manifest['archive_sha256']
    return {'head': manifest['head'], 'files': len(manifest['source_facts']),
            'archive_sha256': manifest['archive_sha256']}


def main(kind: str, metadata: Path, destination: Path, expected_sha256: str,
         comparison: Path | None = None) -> None:
    """Keep the original semantic checks and make copy lifetime explicit."""
    assert kind in SPECS
    destination.mkdir(exist_ok=False)
    original = json.loads(metadata.read_text())
    assert original['archive_sha256'] == expected_sha256
    assert original['artifact']['digest'] == 'sha256:' + expected_sha256
    reader_name, source_manifest = SPECS[kind]
    manifest = json.loads((BASE / source_manifest).read_text())
    assert original['artifact']['workflow_run']['head_sha'] == manifest['head']
    held = source_guard(manifest)
    reader_path = BASE / '2026-10-26' / reader_name
    spec = importlib.util.spec_from_file_location('native_original_byte_auditor', reader_path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    assert reader.SOURCE == Path(manifest['root']) and reader.HEAD == manifest['head']
    # BUILD is solely the local index/output anchor. All checker functions,
    # original runner paths, source/SDK expectations and refusal rules stay intact.
    reader.BUILD = destination
    archive = Path(original['archive'])
    with temporary.staged(archive, expected_sha256, namespace='native-' + kind) as staged:
        index = original | staged
        root = Path(index['root'])
        if kind == 'metric':
            language, start = original['language'], original['start']
            prefix = language + '-' + start
            index_path = destination / (prefix + '-selected-index-04.json')
            result_path = destination / (prefix + '-raw-audit-06/review.json')
            arguments = (language, start, '04', expected_sha256)
        else:
            prefix = original['case']
            index_path = destination / (prefix + '-selected-index-01.json')
            result_path = destination / (prefix + '-raw-audit-02/review.json')
            arguments = (prefix, expected_sha256)
        index_path.write_text(json.dumps(index, indent=2) + '\n')
        reader.main(*arguments)
        result = json.loads(result_path.read_text())
        assert result['new_application_launches'] == result['compiler_builds'] == result['sdk_builds'] == 0
        if comparison is not None:
            assert result == json.loads(comparison.read_text()), 'original auditor result changed'
        storage = index['working_storage']
    assert not root.exists(), 'temporary working tree was not removed'
    assert source_guard(manifest) == held
    receipt = {'status': 'pass through unchanged original native byte auditor', 'kind': kind,
        'case': prefix, 'source_preservation': held, 'original_archive': str(archive),
        'original_archive_sha256': expected_sha256, 'original_reader': str(reader_path),
        'original_reader_sha256': selection.sha256(reader_path),
        'temporary_helper_sha256': selection.sha256(Path(temporary.__file__)),
        'original_selection_verifier_sha256': selection.sha256(Path(selection.__file__)),
        'checker_configuration': {'BUILD': str(destination)}, 'audit_record': str(result_path),
        'audit_record_sha256': selection.sha256(result_path),
        'comparison': None if comparison is None else str(comparison),
        'complete_original_result_identical': comparison is not None,
        'selected_logical_files': index['selected_members'],
        'selected_logical_bytes': index['selected_bytes'], 'working_storage': storage,
        'temporary_root_removed': True, 'retained_byte_source': 'Original caller-pinned ZIP; temporary copies are disposable',
        'new_application_launches': 0, 'compiler_builds': 0, 'sdk_builds': 0,
        'scope': 'Original bytes, outcomes and raw receipt only. Runner inode/UID/time/kernel facts remain historical data. Temporary working files do not reproduce runner filesystem identities.'}
    (destination / 'working-set-review.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    assert len(sys.argv) in (5, 6)
    main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4],
         None if len(sys.argv) == 5 else Path(sys.argv[5]))
