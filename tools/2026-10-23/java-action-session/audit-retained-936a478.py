"""Recheck the fixed interoperability's build, origins and fixed launch inputs.

No application is started. This remains fixed-workload evidence, without
generated-provider or shipping admission.
"""

import hashlib
import json
from pathlib import Path
import shutil
import sys

CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-session/source-936a478')
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples')]
import java_build
import java_launch
import java_profiles
import java_provider
import java_witness

ROOT = Path(__file__).resolve().parent / sys.argv[1]
SDK = Path(sys.argv[2]).resolve(strict=True)
BUILD = ROOT / 'build'
CLASSES = BUILD / 'scratch/classes'
JAVA = Path('/opt/homebrew/opt/openjdk@21/bin/java').resolve(strict=True)
ENTRY = {'path': 'ActionFixture.java', 'otelc_function': 'ActionFixture.target(int)'}


def read(path: Path) -> dict:
    """Read retained strict JSON with the same independent consumer reader."""
    return java_launch.capture.strict_json(path.read_bytes())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


java_build.verify(ROOT / 'project', CLASSES, BUILD)
application = read(BUILD / java_launch.APPLICATION_FILE)
bindings = read(ROOT / 'bindings/bindings.json')
proof = read(ROOT / 'proof.json')
lanes = []
for summary in proof['lanes']:
    folder = ROOT / (('plain' if summary['plain'] else 'instrumented') + '-' + str(summary['repeat']))
    retained = folder / 'sdk-runtime'
    archive = read(folder / 'runtime-archive.json')
    runtime = Path(archive['original'])
    launch = read(folder / 'launch.json')
    policy = read(folder / 'policy.json')
    expected_policy = java_provider.configuration(ENTRY, policy['export']['endpoint'],
        'oteleq-action-interop-' + ('plain' if summary['plain'] else 'sdk') + '-' + str(summary['repeat']))
    expected_policy['context'] = {'tasks': False, 'http': False}
    assert policy == expected_policy
    java_launch.verify_identity(launch, application, [CLASSES], runtime, policy, summary['plain'], False)
    java_launch.verify_application(launch['application'], application, BUILD / java_launch.APPLICATION_FILE, CLASSES)
    assert launch['argv'] == read(folder / 'expected-argv.json')
    java_launch.origins(retained, BUILD, ENTRY)
    loaded = read(BUILD / 'verified-origins.json')
    assert set(loaded) == set(application['bindings'])
    shutil.copyfile(BUILD / 'verified-origins.json', folder / 'verified-origins.json')

    expected_tooling = {JAVA}
    if not summary['plain']:
        expected_tooling.update({SDK / java_provider.AGENT, SDK / java_provider.EXTENSION,
            SDK / java_profiles.PATCH, SDK / java_provider.HELPER, ROOT / 'bindings/bindings.json',
            *(runtime / name for name in ('agent.properties', 'plan.properties', 'selection.json',
                                         'witness.properties', 'witness.json'))})
        selection = {'methods': {'ActionFixture': ['target']}, 'types': [], 'resources': []}
        assert read(retained / 'selection.json') == selection
        values = java_launch.agent_values(policy, 'ActionFixture', 'target', java_profiles.SAFE)
        values.update({key: 'false' for key in ('otel.instrumentation.executors.enabled',
            'otel.instrumentation.java-http-client.enabled', 'otel.instrumentation.java-http-server.enabled',
            'otel.instrumentation.otelc-http-headers.enabled')})
        assert (retained / 'agent.properties').read_text() == java_launch.properties(values)
        assert (retained / 'plan.properties').read_text() == java_launch.properties(
            java_launch.plan_values(runtime, policy, selection))
        values = {'schema_version': '3', 'profile': java_witness.HANDLE_PROFILE,
            'socket': str(runtime / 'witness.sock'), 'build': java_provider.digest(launch['application']),
            'selection': java_provider.digest(selection), 'policy': java_provider.digest(policy),
            'tooling': java_provider.digest(launch['tooling'][:-2])}
        for role, binding in bindings['bindings'].items():
            values.update({role + '.' + key: value for key, value in binding.items()})
            values[role + '.origin'] = CLASSES.as_uri().replace('file:///', 'file:/', 1) + '/'
        values.update({'route.' + key: str(value) for key, value in bindings['route'].items()})
        assert (retained / 'witness.properties').read_text() == java_launch.properties(values)
        expected_metadata = {'schema_version': 3, 'kind': 'otelc.java-witness-launch',
            'profile': java_witness.HANDLE_PROFILE, 'socket': values['socket'],
            'final_report': str(runtime / 'witness-health.json'),
            **{name + '_sha256': values[name] for name in ('build', 'selection', 'policy', 'tooling')},
            'route': bindings['route'],
            'bindings': bindings['bindings'], 'bindings_sha256': digest(ROOT / 'bindings/bindings.json'),
            'runtime_confirmation_required': True, 'receiver_confirmation_required': True}
        assert read(retained / 'witness.json') == expected_metadata
    rows = launch['tooling']
    assert len(rows) == len(expected_tooling) and {Path(row['path']) for row in rows} == expected_tooling
    for row in rows:
        path = Path(row['path'])
        if path.is_relative_to(runtime):
            relative = path.relative_to(runtime).as_posix()
            assert row == archive['files'][relative]
            saved = retained / relative
            assert saved.stat().st_size == row['size'] and digest(saved) == row['sha256']
        else:
            java_launch.files([row], {path})
    lanes.append({'pid': summary['pid'], 'origins': loaded, 'fixed_configuration_and_tooling_verified': True})

result = {'consumer_head': proof['consumer_head'], 'producer_head': proof['producer_head'],
    'proof_sha256': digest(ROOT / 'proof.json'), 'application_started': False,
    'compiler_source_products_and_jdk_reverified': True, 'lanes': lanes,
    'scope': 'retained fixed interoperability audit; generated and shipping admission remain unavailable'}
(ROOT / 'retained-audit.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'lanes': len(lanes), 'loaded_class_checks': sum(len(row['origins']) for row in lanes),
    'retained_audit_sha256': digest(ROOT / 'retained-audit.json')}))
