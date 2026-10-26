"""Check newly discovered scalar functions in all eight languages after relocation."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'reviewed-source-03b9658/tests'))
import qualify_project_tests as fixture
import project_fixture_oracle as oracle


def main() -> None:
    assert not sys.flags.optimize
    cli = ROOT / 'quux-oteleq-03b9658'
    provider = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
    folder = ROOT / 'added-after-promotion'
    folder.mkdir(mode=0o700, exist_ok=False)
    os.environ.update(OTELEQ_CLI=str(cli), OTELEQ_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1')
    application = fixture.make_application(folder)
    policy = folder / 'policy.toml'
    policy.write_text('schema_version=1\n[generation]\ncases_per_function=1\n[functions]\ninclude=["*current_added*"]\n')
    workspace = Path(fixture.command([cli, 'plan', '--source', application, '--otelc-root', provider,
        '--workspace-parent', folder, '--config', policy], folder, 'plan'))
    fixture.command([cli, 'generate', '--workspace', workspace], folder, 'generate')
    bundle = application / 'equivalence-tests'
    fixture.command([cli, 'promote', '--workspace', workspace, '--source', application,
        '--destination', bundle, '--apply'], folder, 'promote')
    original_plan = json.loads((workspace / 'plan.json').read_text())
    assert not any(entry['status'] in ('ready', 'blocked') for entry in original_plan['inventory'])
    assert json.loads((workspace / 'tests/corpus.json').read_text()) == []
    fixture.command([sys.executable, '-I', '-B', bundle / 'test_equivalence.py'], folder, 'empty-before', 1,
        {'OTELEQ_SOURCE': '', 'OTELEQ_WORKSPACE_PARENT': str(folder)})
    assert not list(folder.rglob('typed-observation.json'))
    assert 'Ran 1 test' in (folder / 'empty-before.stderr').read_text()
    fixture.add_functions(application)
    application = application.rename(folder / 'relocated-application')
    bundle = application / bundle.name
    fixture.command([sys.executable, '-I', '-B', bundle / 'test_equivalence.py'], folder, 'suite',
        environment={'OTELEQ_SOURCE': '', 'OTELEQ_WORKSPACE_PARENT': str(folder)})
    records = [json.loads(line) for line in (folder / 'suite.stdout').read_text().splitlines()]
    assert len(records) == 9
    fresh = Path(records[0]['workspace'])
    plan = json.loads((fresh / 'plan.json').read_text())
    ready = [entry for entry in plan['inventory'] if entry['status'] == 'ready']
    assert len(ready) == 8 and {entry['language'] for entry in ready} == set(fixture.LANGUAGES)
    assert all('current_added' in entry['name'] for entry in ready)
    assert not any(entry['status'] == 'blocked' for entry in plan['inventory'])
    assert plan['source_manifest'] == fixture.application_sources(application)
    seen, cases = set(), set()
    for record in records[1:]:
        case, attempts = oracle.check_report(Path(record['report']), 'added')
        assert case not in cases and seen.isdisjoint(attempts)
        seen |= attempts
        cases.add(case)
    assert len(seen) == 32 and 'Ran 8 tests' in (folder / 'suite.stderr').read_text()
    fixture.write(folder / 'qualification.json', {'status': 'complete', 'scope': 'Eight functions discovered after promotion and checkout relocation; empty-before suite fails without app launches',
        'claim': 'equivalence over these tests and observations', 'cli_sha256': fixture.digest(cli),
        'cases': 8, 'actual_launches': 32, 'attempts': sorted(seen),
        'original_failed_preflight_retained': str(ROOT / 'preflight-failure-summary.json'),
        'full_project_qualification_complete': False})


if __name__ == '__main__':
    main()
