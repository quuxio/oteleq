"""Join all original native shards with complete, unique launch denominators."""

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zipfile

ROOT = Path('/Users/sclarke/github/oteleq-qualification')
DAY = ROOT / '2026-10-26'


def sha(path: Path) -> str:
    """Hash a complete original file as a stream."""
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def cohort(kind: str) -> tuple[dict, set]:
    """Audit every expected shard reference and join actual original launch IDs."""
    metric = kind == 'metric'
    folder = DAY / ('native-metric-5ff52e0' if metric else 'native-lifetime-d1b1a0e')
    previous = json.loads((folder / ('partial-six-shards-audit-06.json' if metric
                                    else 'partial-nine-shards-audit-02.json')).read_text())
    specs = {row['case']: (Path(row['record']), row['sha256'], None) for row in previous['shards']}
    extras = ('cpp00', 'cpp10') if metric else ('throwing-destructor',)
    for label in extras:
        version = '03' if label == 'cpp00' else '01'
        wrapper_path = DAY / f'native-temporary-{label}-audit-{version}/working-set-review.json'
        wrapper = json.loads(wrapper_path.read_text())
        assert wrapper['status'] == 'pass through unchanged original native byte auditor'
        assert wrapper['temporary_root_removed'] and not Path(json.loads(
            next(wrapper_path.parent.glob('*-selected-index-*.json')).read_text())['root']).exists()
        assert sha(Path(wrapper['original_reader'])) == wrapper['original_reader_sha256']
        specs[wrapper['case']] = (Path(wrapper['audit_record']), wrapper['audit_record_sha256'], wrapper_path)
    expected = ({f'{language}-{start}' for language in ('c', 'cpp') for start in ('00', '01', '10', '11')}
                if metric else {'c-completed', 'cpp-completed', 'cpp-target-error', 'c-state',
                                'c-zero', 'cpp-zero', 'c-censored', 'cpp-censored', 'cpp-unwind',
                                'cpp-throwing-destructor'})
    assert set(specs) == expected
    artifacts = json.loads((DAY / f'native-archive-provenance-01/{kind}-artifacts.json').read_text())['artifacts']
    all_ids, rows, totals, raw_totals = set(), [], Counter(), Counter()
    numeric = (('distinct_application_records', 'instrumented_receipts', 'archived_reports_audited',
                'promotion_reports', 'actual_altered_capture_refusals', 'selected_original_files_preserved')
               if metric else ('actual_application_launch_records', 'instrumented_raw_receipts', 'reports',
                               'current_source_promotion_reports', 'fresh_altered_copy_refusals',
                               'selected_evidence_files_preserved'))
    for case in sorted(expected):
        record, expected_digest, wrapper_path = specs[case]
        assert sha(record) == expected_digest
        data = json.loads(record.read_text())
        assert data['head'] == previous['head'] and data['status'].startswith('pass')
        assert data['new_application_launches'] == data['compiler_builds'] == data['sdk_builds'] == 0
        assert (data['language'] + '-' + data['start'] if metric else data['case']) == case
        artifact, = [row for row in artifacts if row['digest'] == 'sha256:' + data['archive_sha256']]
        assert artifact['workflow_run']['head_sha'] == previous['head'] and not artifact['expired']
        index_path = (next(wrapper_path.parent.glob('*-selected-index-*.json')) if wrapper_path is not None
                      else folder / (case + ('-selected-index-04.json' if metric else '-selected-index-01.json')))
        index = json.loads(index_path.read_text())
        assert index['archive_sha256'] == data['archive_sha256']
        archive = Path(index['archive'])
        assert archive.stat().st_size == artifact['size_in_bytes'] and sha(archive) == data['archive_sha256']
        with zipfile.ZipFile(archive) as bundle:
            original = json.loads(bundle.read(f'native-{kind}-evidence/qualification.json'))
        assert original['consumer_source'] == previous['head']
        ids = set(original['audit']['records'])
        assert len(ids) == data[numeric[0]] == original['audit']['actual_application_records']
        assert all(re.fullmatch('[a-f0-9]{32}', identity) for identity in ids)
        assert not all_ids.intersection(ids), 'a launch was counted in more than one shard'
        assert sum(row['plain'] is False for row in original['audit']['records'].values()) == data[numeric[1]]
        all_ids.update(ids)
        totals.update({key: data[key] for key in numeric})
        raw_totals.update(data['complete_raw_totals' if metric else 'raw_totals'])
        rows.append({'case': case, 'record': str(record), 'sha256': expected_digest,
                     'archive': str(archive), 'archive_sha256': data['archive_sha256'],
                     'artifact': artifact['id'], 'launch_ids': len(ids),
                     'temporary_working_set_review': None if wrapper_path is None else str(wrapper_path),
                     **{key: data[key] for key in numeric}})
    assert len(all_ids) == totals[numeric[0]] == (944 if metric else 296)
    assert totals[numeric[1]] == (472 if metric else 148)
    assert totals[numeric[4]] == (392 if metric else 140)
    result = {'status': 'complete original captured-byte corpus; independent runtime review pending',
              'head': previous['head'], 'shards': rows, 'totals': dict(totals),
              'complete_raw_totals': dict(raw_totals), 'unique_launch_ids': len(all_ids),
              'launch_ids_sha256': hashlib.sha256(json.dumps(sorted(all_ids), separators=(',', ':')).encode()).hexdigest(),
              'required_shards': len(expected), 'complete_corpus': True,
              'peer_review': 'pending for complete runtime corpus and temporary-copy adapter',
              'new_application_launches': 0, 'compiler_builds': 0, 'sdk_builds': 0,
              'scope': 'All named original shards, exact original source and diagnostic workflows only. Original ZIPs persist; three new selected trees were temporary. Historical runner stat/kernel/image execution is not recertified. Broader source shapes, platforms, current SDK replacements and shipping remain separate.'}
    destination = folder / ('complete-eight-shards-aggregate-02.json' if metric else 'complete-ten-shards-aggregate-02.json')
    assert not destination.exists()
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(kind, len(expected), dict(totals), sha(destination))
    return result, all_ids


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('source_guard', DAY / 'audit_native_temporary_working_set.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    manifests = [json.loads((ROOT / path).read_text()) for path in (
        '2026-10-25/native-metric-controls/source-5ff52e0.json',
        '2026-10-25/native-lifetime-build/source-d1b1a0e.json')]
    before = [guard.source_guard(manifest) for manifest in manifests]
    metric, metric_ids = cohort('metric')
    lifetime, lifetime_ids = cohort('lifetime')
    assert not metric_ids.intersection(lifetime_ids)
    assert [guard.source_guard(manifest) for manifest in manifests] == before
    assert len(metric_ids | lifetime_ids) == 1240
    print('All1240 launch IDs are unique; all1396 original source files/archive facts held.')
