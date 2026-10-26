"""Publish frozen generated-action evidence with separate producer defect history."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-generated-actions')
RECORD = 'docs/qualification/java-generated-actions-2026-10-24.json'
HOST = Path('/Users/sclarke/github/oteleq-qualification/2026-10-22/node-source-consumer-0f05020/validation-hash-env/bin/python')
CLI = ROOT / 'runtime-479f266/target/debug/quux-oteleq'


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    assert Path(sys.executable) == HOST and not sys.flags.optimize
    source = read(ROOT / 'source-479f266.json')
    assert source['head'] == subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    assert all(sha(REPO / name) == digest for name, digest in source['files'].items())
    provider = read(ROOT / 'provider-completion-42258a4.json')
    sdk = ROOT / 'provider-completion-42258a4'
    assert len(provider['files']) == 362
    assert all(sha(sdk / name) == digest for name, digest in provider['files'].items())
    assert all(sha(sdk / name) == product['sha256'] for name, product in provider['products'].items())
    sys.path[:0] = [str(REPO / 'adapters/generation'), str(REPO / 'examples')]
    import generation
    import java_build
    import java_provider

    old_bytes = subprocess.check_output(['git', '-C', str(REPO), 'show', '843eb9afcb60168560d64ed38e529d80cce5ac50:' + RECORD])
    record = json.loads(old_bytes)
    (ROOT / 'publication-draft/java-generated-actions-clock-history.json').write_bytes(old_bytes)
    corpora, launches = [], set()
    for profile in ('safe', 'archive'):
        name = f'qualified-479f266-completion-42258a4-{profile}'
        folder = ROOT / name
        value, inputs = read(folder / 'qualification.json'), read(folder / 'inputs.json')
        retained = ROOT / f'retained-479f266-completion-42258a4-{profile}-314.log'
        assert read(retained) == value and value['source_preserved']
        assert (value['reports'], value['distinct_application_launches'], value['complete_boundary_graphs'],
                value['action_scopes'], value['spans'], value['altered_evidence_refusals']) == (19, 80, 564, 94, 426, 16)
        assert inputs['cli_sha256'] == sha(CLI) and inputs['consumer'] == generation.generator_identity()
        assert all(sha(REPO / 'tests' / file) == digest for file, digest in inputs['qualifier'].items())
        java = Path('/opt/homebrew/opt/openjdk@21/bin/java').resolve(strict=True)
        tools = {'java': java, 'javac': java.with_name('javac'), 'java-modules': java_build.module_image(java)}
        if profile == 'archive':
            tools['javap'] = java.with_name('javap')
        assert java_provider.artefacts(sdk, tools, inputs['java_profile'], action=True) == inputs['sdk']
        identities = set()
        for route in read(folder / 'routes.json'):
            report = Path(route['report'])
            for case in read(report)['cases']:
                for lane in ('baseline', 'instrumented_on'):
                    for index in range(2):
                        process = read(report.parent / case['case'] / f'{lane}-{index}' / 'process.json')
                        assert type(process['pid']) is int and process['pid'] > 0
                        identities.add((process['pid'], hashlib.sha256(json.dumps(process['argv']).encode()).hexdigest()))
        assert len(identities) == 80 and not launches.intersection(identities)
        launches.update(identities)
        corpora.append({
            'java_profile': value['java_profile'],
            **{key: value[key] for key in ('reports', 'distinct_application_launches', 'complete_boundary_graphs',
                                          'action_scopes', 'spans', 'altered_evidence_refusals', 'source_preserved')},
            'consumer_inputs_sha256': inputs['consumer'],
            'sdk_input_map_sha256': hashlib.sha256(json.dumps(inputs['sdk'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'sdk_input_files': sum(not key.startswith('tool:') for key in inputs['sdk']),
            'tool_files': sum(key.startswith('tool:') for key in inputs['sdk']),
            'launch_identity_set_sha256': hashlib.sha256(json.dumps(sorted(identities), separators=(',', ':')).encode()).hexdigest(),
            'qualification_sha256': sha(folder / 'qualification.json'),
            'input_manifest_sha256': sha(folder / 'inputs.json'),
            'route_manifest_sha256': sha(folder / 'routes.json'),
            'refusal_summary_sha256': sha(folder / 'refusals/summary.json'),
            'python_314_retained_audit_sha256': sha(retained),
        })
    assert len(launches) == 160
    safe_inputs = read(ROOT / 'qualified-479f266-completion-42258a4-safe/inputs.json')
    record.update(
        scope_status='qualified recorded synchronous generated private static and receiver action workflows on the frozen clock- and completion-fixed provider',
        runtime={'repository': 'quuxio/oteleq', 'commit': source['head'], 'source_archive_sha256': source['archive_sha256'],
                 'source_files_preserved': len(source['files']), 'cli_sha256': safe_inputs['cli_sha256'],
                 'generator_inputs_sha256': safe_inputs['consumer']},
        verifier={'commit': source['head'], 'qualifier_introduced_commit': '9edbb66f598862443a39b0134229933b21dd0991',
                  'entrypoint': 'tests/qualify_java_generated_actions.py', 'retained_option': '--retained-only',
                  'qualifier_files_sha256': safe_inputs['qualifier']},
        provider={'repository': 'quuxio/otelc', 'commit': provider['head'], 'base': provider['base'],
                  'delivery_status': 'recorded candidate; final merged-provider compatibility is separate',
                  'source_archive_sha256': provider['archive_sha256'], 'source_files_preserved': len(provider['files']),
                  'products': provider['products'], 'all_products_preserved': True},
        corpora=corpora,
    )
    # Keep the earlier actual clock defect attributed to its original producer and fix.
    assert record['detected_provider_defect']['provider_commit'] == '1b02dbc1db6c567cc684293e68d098e794546007'
    assert record['detected_provider_defect']['fix_commit'] == provider['base']
    completion = ROOT.parent / 'java-completion-review-42258a4'
    component = read(completion / 'review.json')
    assert component['head'] == provider['head'] and not component['findings']
    record['additional_provider_component'] = {
        'kind': 'original_completion_error_preservation', 'base': provider['base'], 'fix_commit': provider['head'],
        'independent_java_tests_passed': component['independent_clean_maven']['tests'],
        'java_line_coverage_percent': component['independent_clean_maven']['line_coverage_percent'],
        'independent_unchanged_production_regressions_failed': len(component['unchanged_production_negative_control']['failed_tests']),
        'independently_rebuilt_provider_classes_matched': component['provider_class_rebuild']['class_files'],
        'actual_agent_tests_each_python_runtime': 2, 'python_runtimes': ['3.12.15', '3.14.8'],
        'review_sha256': sha(completion / 'review.json'),
        'scope': 'Supported JDK completion stages preserve the original future/throwable without application formatting; custom stages, broader async attribution and task propagation remain outside this component',
    }
    record['review'] = {
        'consumer_verdict': 'clear through reviewed integration, maintained qualification, publication and interval-diagnostic deltas',
        'consumer_review_chain_sha256': {name: sha(ROOT / name) for name in
            ('independent-review-49d8ff1.json', 'independent-review-d53377e.json',
             'independent-review-843eb9a.json', 'independent-review-479f266.json')},
        'sdk_clock_component_review_sha256': sha(ROOT.parent / 'java-clock-review-45b7564/review.json'),
        'sdk_completion_component_review_sha256': sha(completion / 'review.json'),
        'scope': 'Recorded revisions and component boundaries; final publication review and merged-main delivery remain separate',
    }
    full = read(ROOT / 'full-gate-479f266/result.json')
    assert full['head'] == source['head'] and full['exit_code'] == 0 and full['source_preserved'] and full['tracked_files_checked'] == 479
    assert 'Ran 1090 tests' in (ROOT / 'full-gate-479f266/make-check.log').read_text()
    record['validation'] = {
        'full_gate_commit': source['head'], 'generation_tests': 1090, 'rust_product_line_coverage_percent': 97.38,
        'full_gate_result_sha256': sha(ROOT / 'full-gate-479f266/result.json'),
        'full_gate_log_sha256': sha(ROOT / 'full-gate-479f266/make-check.log'),
    }
    output = json.dumps(record, indent=2) + '\n'
    (REPO / RECORD).write_text(output)
    (ROOT / 'publication-draft/java-generated-actions-completion-record.json').write_text(output)
    current_path = ROOT / 'CURRENT.json'
    current = read(current_path)
    current.update(state='final_runtime_and_provider_qualified_publication_in_progress', running={},
                   full_gate=full, full_gate_generation_tests=1090,
                   remaining=['Final qualification publication and independent review',
                              'SDK215/216 protected main delivery and exact merged-provider compatibility',
                              'Final-head/main checks, merge and hygiene', 'All other open rows in docs/completion.md'])
    for profile, corpus in zip(('safe', 'archive'), corpora):
        current['qualification']['completion_' + profile] = corpus
    for name in ('full-gate-479f266/result.json', 'full-gate-479f266/make-check.log', 'source-479f266.json'):
        current['proof_sha256'][name] = sha(ROOT / name)
    current['completion_component_review'] = {'review_sha256': sha(completion / 'review.json'), 'head': provider['head'],
                                             'verdict': component['verdict']}
    current_path.write_text(json.dumps(current, indent=2) + '\n')
    print(json.dumps({'record': str(REPO / RECORD), 'sha256': sha(REPO / RECORD), 'runtime': source['head'],
                      'provider': provider['head'], 'actual_jvms': len(launches), 'source_files_preserved': len(source['files'])}))


if __name__ == '__main__':
    main()
