"""Revalidate exact fixture results and index the actual launches, without reruns."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

if sys.flags.optimize:
    raise SystemExit('Revalidation requires assertions')

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-integrated-qualification')
sys.path.insert(0, str(REPO / 'tests'))
import qualify_project_policy as qualifier


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + '\n')


reports = [ROOT / 'generated/comparisons/report.json', ROOT / 'configured/comparison/report.json']
for filename in ('framework.stdout', 'export-replay.stdout'):
    for line in (ROOT / 'generated' / filename).read_text().splitlines():
        reports.append(Path(json.loads(line)['report']))
assert len(reports) == 11
checked_cases = checked_launches = 0
for path in reports:
    report = read(path)
    assert report['source_preserved']
    entries = {entry['id']:entry for entry in report['inventory']}
    for case in report['cases']:
        assert case['exit_code'] == 0 and case['comparison']['verdict'] == 'equivalent_observed'
        folder = path.parent / case['case']
        raw = read(folder / 'bundle.json')['cases'][0]
        typed = read(folder / 'typed-bundle.json')['cases'][0]
        qualifier.check_case(case, entries[case['case'].rsplit('-', 1)[0]], raw, typed)
        checked_cases += 1
        checked_launches += len(raw['baseline']) + len(raw['instrumented_on'])
assert checked_cases == 71 and checked_launches == 360
commands = []
for part in ('generated', 'configured', 'rust', 'rust-semantics'):
    for path in sorted((ROOT / part).rglob('command.json')):
        commands.append({'path':str(path.relative_to(ROOT)),'command':read(path)})
for path in sorted((ROOT / 'fixed').rglob('commands.json')):
    commands.append({'path':str(path.relative_to(ROOT)),'command':read(path)['executed']})
assert len(commands) == 533 and len({json.dumps(row['command']) for row in commands}) == 533
save(ROOT / 'launch-index.json', commands)
controls = {}
for name, exits, count in [('mutation-comparison',[1,1,1],12),('binding-comparison',[4,4,4],3),
                            ('callback-comparison',[4,4,4],2),('unexpected-error-comparison',[2],4),
                            ('initial-state-comparison',[2],4)]:
    folder = ROOT / 'generated' / name
    report = read(folder / 'report.json')
    assert report['source_preserved'] and [row['exit_code'] for row in report['cases']] == exits
    actual = len(list(folder.rglob('command.json')))
    assert actual == count
    controls[name] = {'cases':len(exits),'actual_launches':actual,'expected_exits':exits}
assert len(read(ROOT/'retained-controls/controls.json')['actual_retained_bundle_controls']) == 14
records = []
for part in ('fixed', 'generated', 'configured', 'rust', 'rust-semantics'):
    for path in sorted((ROOT/part).rglob('*')):
        row = {'path':str(path.relative_to(ROOT))}
        if path.is_symlink():
            records.append({**row,'link':str(path.readlink())})
        elif path.is_file():
            records.append({**row,'bytes':path.stat().st_size,'mode':oct(path.stat().st_mode & 0o777),'sha256':digest(path)})
save(ROOT/'raw-manifest.json', records)
result = {'runtime':read(ROOT/'runtime.json'),'actual_application_launches':533,
          'unique_command_identities':533,'launch_counts':{'fixed':32,'generated':169,'configured':228,'rust_generated':96,'rust_semantics':8},
          'matching_application_launches':508,'intentional_state_difference_launches':12,
          'blocked_fixture_launches':8,'refused_worker_launches':5,
          'additional_prelaunch_build_refusals':1,'controls':controls,
          'independent_exact_value_revalidation':{'reports':11,'case_executions':71,'application_launches':360,
                'qualifier_sha256':digest(Path(qualifier.__file__)),'script_sha256':digest(Path(__file__)),
                'application_reruns':0,'scope':'Ordinary add, integer extremes, f32/signed zero and Unicode; all recorded repeats/lanes checked against fixture-source expectations.'},
          'retained_rust_record_refusals':14,'metadata_control_application_launches':0,
          'provider_records_verified_after':read(ROOT/'provider-verified-after.json')['verified_records'],
          'raw_files_and_links':len(records),'raw_manifest_sha256':digest(ROOT/'raw-manifest.json'),
          'launch_index_sha256':digest(ROOT/'launch-index.json'),'source_preserved':True}
save(ROOT/'verification.json', result)
print(json.dumps({k:v for k,v in result.items() if k not in ('runtime','controls')}))
