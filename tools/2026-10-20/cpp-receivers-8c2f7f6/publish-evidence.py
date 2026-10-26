"""Publish the completed frozen corpus without changing implementation sources."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
WORK = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-cpp-receivers')


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


runtime = read(ROOT / 'runtime.json')
summary = read(ROOT / 'actual/qualification.json')
verification = read(ROOT / 'verification.json')
assert read(ROOT / 'qualification-exit.json')['exit_code'] == 0
assert read(ROOT / 'full-gate-exit.json')['exit_code'] == 0
assert summary['unique_application_launches'] == verification['unique_application_launches'] == 299
assert summary['raw_attempt_folders'] == verification['raw_attempt_folders'] == 303
assert summary['matching_cases'] == 14 and summary['different_cases'] == 3
assert summary['refusal_controls'] == verification['refusal_reports_verified'] == 11
assert summary['oteleq_cli_sha256'] == runtime['cli_sha256'] == digest(ROOT / 'quux-oteleq')
assert verification['runtime_commit'] == runtime['source_commit']
assert verification['source_preserved']
assert verification['verifier_sha256'] == digest(ROOT / 'verify-evidence.py')
assert read(ROOT / 'provider-verified-before.json')['manifest_sha256'] == read(ROOT / 'provider-verified-after.json')['manifest_sha256']
assert read(ROOT / 'presentation/verified.json')['browser_review'] == 'passed'
macro = read(ROOT / 'actual/refusal-macro-storage/run/report.json')
assert macro['blocked'] and not macro['cases'] and macro['source_preserved']
assert any('macro-expanded' in item['reason'] for item in macro['blocked'])

log = (ROOT / 'full-gate.log').read_text()
python_tests = set(re.findall(r'^test_\w+ \(([^)]+)\) \.\.\.', log, re.M))
rust_tests = set(re.findall(r'^test (\S+) \.\.\. ok$', log, re.M))
node_tests = sum(map(int, re.findall(r'^[#\u2139] tests (\d+)$', log, re.M)))
go_tests = re.findall(r'^func (Test\w+)\(', (ROOT / 'consumer/tests/go_observer_test.go').read_text(), re.M)
assert (len(python_tests), len(rust_tests), node_tests, len(go_tests)) == (414, 66, 17, 4)
assert 'C++ observer line coverage: 100.00%' in log
assert '1737                47    97.29%' in log

record = read(WORK / 'docs/qualification/cpp-receivers-2026-10-20.json')
record['runtime'] = {**runtime, 'provider_commit': read(ROOT / 'provider-verified-after.json')['provider_commit'],
                     'provider_manifest_sha256': read(ROOT / 'provider-verified-after.json')['manifest_sha256'],
                     'generator_sha256': digest(ROOT / 'consumer/adapters/generation/generation.py'),
                     'qualifier_sha256': summary['qualifier_sha256']}
record['runtime'].pop('status')
record['runtime'].pop('claim')
record['provider'] = read(ROOT / 'provider-verified-after.json')
record['provider']['scope'] = 'Content verified before/after this corpus; frozen d6d03b7 identity, not a claim about later producer revisions.'
profiles = {}
for name, folder in (('receivers', 'cases'), ('bindings', 'bindings'), ('crlf', 'crlf/bindings')):
    plans = list((ROOT / 'actual' / folder).glob('oteleq-run-*/plan.json'))
    assert len(plans) == 1
    plan = read(plans[0])
    counts = Counter(item['status'] for item in plan['inventory'])
    profiles[name] = {'callables': len(plan['inventory']), **{key: counts[key] for key in ('ready', 'excluded', 'blocked')}}
record['inventory'] = profiles['receivers']
record['profile_inventories'] = profiles
record['results'].update(cases=17, matching_cases=14, actual_application_launches=299,
                         qualified_application_launches=292, retained_attempt_folders=303,
                         unique_command_identities=299, refusal_controls=11, prelaunch_refusals=7)
record['results']['profiles'] = {'receiver_cases': 9, 'binding_cases': 4, 'crlf_cases': 4}
record.pop('accounting_revalidation', None)
record['driver'] = {'exit_code': 0, 'application_relaunches_for_retained_verification': 0,
                    'shrink_accounting': 'Fresh original replay counts once; four copied records do not count as additional launches.'}
record['independent_verification'] = verification
record['validation'].update(runtime_commit=runtime['source_commit'], unique_regressions=501,
                            python_regressions=414, rust_regressions=66, node_regressions=17, go_regressions=4,
                            rendered_html_and_junit='passed', unresolved_sonar_findings=0)
record['scope']['observed'] += ' Global source type names, C-linkage underscore identities, direct construction of small self-referential objects and CRLF source ranges are exercised separately.'
record['scope']['not_qualified'].append('macro-expanded callables or storage beyond explicit refusal')
(WORK / 'docs/qualification/cpp-receivers-2026-10-20.json').write_text(json.dumps(record, indent=2) + '\n')

for relative in ('README.md', 'docs/receiver-fixtures.md', 'docs/completion.md', 'docs/automatic-generation.md'):
    path = WORK / relative
    old = path.read_text()
    assert '171-launch diagnostic qualification' in old
    path.write_text(old.replace('171-launch diagnostic qualification', '299-launch diagnostic qualification'))

path = WORK / 'docs/quality.md'
old = path.read_text()
before = 'verifies nine cases/171 unique application launches and ten refusal controls on the recorded macOS ARM64/LLVM 22 provider. Its retained revalidation corrects aggregate copied-attempt accounting without relaunching applications;'
after = 'verifies 17 cases/299 unique application launches and eleven refusal controls on the recorded macOS ARM64/LLVM 22 provider. The frozen driver exits successfully; retained verification checks actual binaries, source copies, complete independent value oracles and copied shrink accounting;'
assert before in old
path.write_text(old.replace(before, after))

path = WORK / 'docs/cpp-receivers.md'
old = path.read_text()
start = old.index('The [exact-revision macOS ARM64 record]')
end = old.index('\n\nThe claim remains', start)
replacement = ('The [exact-revision macOS ARM64 record](qualification/cpp-receivers-2026-10-20.json) covers 17 cases and 299 unique application launches: 14 matches, three deliberate differences, fixed construction through scalar shrinking/replay and eleven refusal controls. Separate binding and CRLF groups exercise a global application class named `Graph`, small self-referential construction and C-linkage names with application underscores. It records 303 attempt folders because four original shrink attempts are copied. The frozen driver exits successfully; retained verification checks every report, original/copy relationship, binary, source and complete value oracle without relaunching applications. Macro-expanded storage is refused before application launch. This qualifies the recorded diagnostic runtime/provider profile; other platforms and shipping builds remain open.')
path.write_text(old[:start] + replacement + old[end:])

changed = subprocess.check_output(['git', 'diff', '--name-only', runtime['source_commit']], cwd=WORK, text=True).splitlines()
assert all(name.endswith('.md') or name == 'docs/qualification/cpp-receivers-2026-10-20.json' for name in changed)
print(json.dumps({'published_runtime': runtime['source_commit'], 'changed_documentation': changed}))
