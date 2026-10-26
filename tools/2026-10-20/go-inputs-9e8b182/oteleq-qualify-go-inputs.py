"""Qualify frozen Go module inputs against actual paired execution."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(arguments, destination, name, expected=0):
    result = subprocess.run([str(value) for value in arguments], capture_output=True,
                            timeout=900, check=False)
    (destination / (name + '.stdout')).write_bytes(result.stdout)
    (destination / (name + '.stderr')).write_bytes(result.stderr)
    assert result.returncode == expected, (name, result.returncode, expected)
    return result.stdout.decode().strip()


def verify_report(path):
    report = json.loads(path.read_text())
    assert report['source_preserved'] and not report['blocked']
    assert len(report['cases']) == 1 and report['cases'][0]['exit_code'] == 0
    case = report['cases'][0]
    bundle = json.loads((path.parent / case['case'] / 'typed-bundle.json').read_text())['cases'][0]
    launches = 0
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        for attempt in bundle[lane]:
            launches += 1
            observation = attempt['observation']
            assert not observation['gaps'] and observation['outcome']['kind'] == 'return'
            result = observation['outcome']['graph']['roots']['result']
            assert result['kind'] == 'integer' and int(result['value']) == 8
    return launches


def main():
    original = Path('/private/tmp/oteleq-integrated-provider-8a7689a')
    provider = Path('/private/tmp/oteleq-go-inputs-provider-8a7689a')
    destination = Path('/private/tmp/oteleq-go-inputs-9e8b182-evidence')
    cli = Path('/private/tmp/oteleq-go-inputs-cli-9e8b182')
    destination.mkdir(mode=0o700, exist_ok=False)
    (provider / 'adapters').mkdir(parents=True, mode=0o700, exist_ok=False)
    (provider / 'target/debug').mkdir(parents=True)
    subprocess.run(['/bin/cp', '-cR', original / 'adapters/go', provider / 'adapters/go'], check=True)
    subprocess.run(['/bin/cp', '-cp', original / 'target/debug/quux-otelc', provider / 'target/debug/quux-otelc'], check=True)
    identities = {str(path.relative_to(provider)): digest(path)
                  for path in provider.rglob('*') if path.is_file()}
    assert all(digest(original / name) == value for name, value in identities.items())
    receipt = {'source_commit': '8a7689a6d6779ed8621bbe852188eeb56e6fafad',
               'scope': 'Private Go-only copy of the frozen unmerged common provider; third-party module caches are outside content identity.',
               'parent_receipt_sha256': digest(original / 'OTELEQ-PROVIDER-SNAPSHOT.json'),
               'files_sha256': identities}
    (provider / 'PROVIDER.json').write_text(json.dumps(receipt, indent=2) + '\n')
    source = destination / 'application'
    source.mkdir()
    (source / 'sample.go').write_text('package main\nfunc sample(value int) int {return value+1}\n')
    source_digest = digest(source / 'sample.go')
    policy = destination / 'equivalence.toml'
    policy.write_text('schema_version=1\nlanguages=["go"]\n[functions]\ninclude=["sample.sample"]\n[[fixtures]]\nlanguage="go"\nfunction="sample.sample"\ncases=[[7]]\n')
    os.environ['OTELEQ_PYTHON'] = sys.executable
    os.environ['OTELEQ_CLI'] = str(cli)
    workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
                              '--workspace-parent', destination, '--config', policy], destination, 'plan'))
    plan = json.loads((workspace / 'plan.json').read_text())
    frozen = plan['artefacts']['go']
    assert 'adapters/go/go.mod' in frozen and 'adapters/go/go.sum' in frozen
    assert any(name.startswith('adapters/go/policy/') for name in frozen)
    command([cli, 'generate', '--workspace', workspace], destination, 'generate')
    command([cli, 'run', '--workspace', workspace, '--report-dir', destination / 'comparison'], destination, 'comparison')
    launches = verify_report(destination / 'comparison/report.json')
    framework = json.loads(command([sys.executable, workspace / 'tests/test_equivalence.py'], destination, 'framework'))
    launches += verify_report(Path(framework['report']))
    controls = []
    module = provider / 'adapters/go/go.mod'
    policy_source = provider / 'adapters/go/policy/policy.go'
    added = provider / 'adapters/go/policy/oteleq_added_control.go'
    for name, path, contents in [('module-edit', module, module.read_bytes() + b'\n// edited identity control\n'),
                                  ('policy-edit', policy_source, policy_source.read_bytes() + b'\n// edited identity control\n'),
                                  ('policy-addition', added, b'package policy\n'),
                                  ('module-missing', module, None)]:
        before = path.read_bytes() if path.exists() else None
        try:
            if contents is None:
                path.unlink()
            else:
                path.write_bytes(contents)
            folder = destination / name
            command([cli, 'run', '--workspace', workspace, '--report-dir', folder], destination, name, expected=4)
            report = json.loads((folder / 'report.json').read_text())
            assert report['source_preserved'] and len(report['cases']) == 1
            assert report['cases'][0]['exit_code'] == 4 and report['cases'][0]['error']
            assert not list(folder.rglob('command.json')) and not list(folder.rglob('observation'))
            controls.append({'name': name, 'exit_code': 4, 'application_launches': 0})
        finally:
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
    assert digest(source / 'sample.go') == source_digest
    assert all(digest(provider / name) == value and digest(original / name) == value
               for name, value in identities.items())
    summary = {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
               'oteleq_runtime': '9e8b182a7a43228ecd48d4e83348be4969cab8ad',
               'oteleq_cli_sha256': digest(cli), 'provider_receipt_sha256': digest(provider / 'PROVIDER.json'),
               'cases': 1, 'actual_application_launches': launches, 'generated_unittest_runs': 1,
               'changed_input_refusals': controls, 'source_preserved': True, 'provider_restored': True,
               'scope': 'Standalone Go scalar with exact module/runtime/policy inputs; no project, third-party cache or shipping qualification.'}
    (destination / 'QUALIFICATION.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
