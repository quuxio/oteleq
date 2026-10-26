"""Check the frozen caller revision on both supported Python runtime families."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
OLD = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-callers')
SOURCE = ROOT / 'source-6314b45'
META = json.loads(SOURCE.with_suffix('.json').read_text())
SDKS = {
    'handles': Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-runtime-review-6fb166c/source-6fb166c'),
    'legacy': Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-review-7815a84/source-7815a84'),
}
RUNTIMES = {
    '312': '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
    '314': '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python',
}
IDS = re.findall(r'^\w+ \((test_[\w.]+)\) \.\.\. ok$', (OLD / 'focused-final-312.log').read_text(), re.M)
IDS += ['test_generation_java_action_bindings.JavaActionBindingsTests.test_compiler_stdout_cannot_replace_the_schema_integer_with_a_float', 'test_generation_java_handle_bindings.JavaHandleBindingTests.test_compiler_stdout_must_preserve_the_retained_route_scalar_types']
IDS += ['test_generation_java_action_session.JavaActionSessionTests.' + name for name in ('test_both_explicit_protocols_bind_before_release_and_keep_outcomes_separate', 'test_baseline_uses_the_same_harness_without_sdk_queries_or_claims', 'test_pending_root_or_export_cannot_release_the_next_action', 'test_foreign_context_or_altered_arm_never_releases_the_call', 'test_failed_or_foreign_end_cannot_advance_the_next_action', 'test_plan_changes_missing_readiness_and_early_exit_remain_incomplete', 'test_missing_or_mistyped_outcomes_cannot_become_receipt_expectations', 'test_invalid_profile_and_independent_input_shapes_refuse_before_control_io', 'test_actual_plain_jvm_runs_the_typed_call_and_final_private_barrier')]
assert len(IDS) == len(set(IDS)) == 88
ENV = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(SOURCE / 'tests'),
       'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
       'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac',
       'PATH': '/opt/homebrew/opt/openjdk@21/bin:' + os.environ['PATH']}


def preserved():
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest
               for name, digest in META['files'].items())


rows = []
for label, python in RUNTIMES.items():
    commands = [('focused', [python, '-m', 'unittest', *IDS, '-v'])]
    for profile, sdk in SDKS.items():
        script = 'qualify_java_handle_bindings.py' if profile == 'handles' else 'qualify_java_action_bindings.py'
        commands.append((profile, [python, str(SOURCE / 'tests' / script), '--otelc-root', str(sdk),
                                   '--report-dir', str(ROOT / (profile + '-' + label + '-6314b45'))]))
    for kind, command in commands:
        log = ROOT / (kind + '-' + label + '-6314b45.log')
        with log.open('wb') as stream:
            result = subprocess.run(command, cwd=SOURCE, env=ENV, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        preserved()
        row = {'runtime': label, 'kind': kind, 'exit_code': result.returncode,
               'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(), 'command': command}
        if result.returncode:
            raise AssertionError(str(log))
        if kind != 'focused':
            record = json.loads((ROOT / (kind + '-' + label + '-6314b45') / 'qualification.json').read_text())
            assert record['application_started'] is False and record['sources_preserved'] is True
            assert len(record['cases']) == (15 if kind == 'handles' else 3)
            if kind == 'handles':
                assert sum(case['accepted'] for case in record['cases']) == 12
            row['cases'] = len(record['cases'])
        rows.append(row)
        (ROOT / 'qualification-6314b45.json').write_text(json.dumps({
            'head': META['head'], 'source_files': len(META['files']), 'source_preserved': True,
            'runs': rows}, indent=2) + '\n')
        print(json.dumps({key: row[key] for key in ('runtime', 'kind', 'exit_code')}), flush=True)
