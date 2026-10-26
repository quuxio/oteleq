"""Record exact source qualification without treating the project as finished."""

import hashlib
import json
from pathlib import Path
import datetime

BASE = Path(__file__).resolve().parent
gate = json.loads((BASE / 'gate-d4c663d.json').read_text())
source = json.loads((BASE / 'source-d4c663d.json').read_text())
focused = [json.loads((BASE / ('focused-' + version + '.json')).read_text()) for version in ('3.12.15', '3.14.8')]
writer = json.loads((BASE / 'writer-interop.json').read_text())
assert gate['head'] == source['head'] == 'd4c663d0f6f86579dfa3ed3b326664db7406439e'
assert gate['exit_code'] == 0 and gate['source_preserved']
assert all(row['exit_code'] == 0 and row['source_preserved'] for row in focused)
assert writer['source_preserved'] and writer['authentic_origin_qualification'] is False
files = ['gate-d4c663d.json', 'gate-d4c663d.log', 'source-d4c663d.tar',
         'source-d4c663d-manifest.json', 'focused-3.12.15.json', 'focused-3.14.8.json',
         'writer-interop.json', 'writer-audit-3.12.15.json', 'writer-audit-3.14.8.json']
review_path = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/oteleq-python-origin-review-d4c663d/review.json')
review = json.loads(review_path.read_text())
merge = json.loads((BASE / 'merge-tree-proof.json').read_text())
pr_checks = json.loads((BASE / 'pr76-head-checks.json').read_text())
main_checks = json.loads((BASE / 'main-checks-435f4d0.json').read_text())
assert review['head'] == gate['head'] and review['decision'] == 'clear' and not review['findings']
assert merge['exact_tree_match'] and merge['merged_by'] == 'quuxio'
assert pr_checks['headRefOid'] == gate['head']
assert all(row['status'] == 'COMPLETED' and row['conclusion'] == 'SUCCESS' for row in pr_checks['statusCheckRollup'])
required = {'Documentation and design examples', 'Rust comparator and 80% product coverage', 'SonarCloud Code Analysis'}
assert main_checks['total_count'] == len(main_checks['check_runs']) == 3
assert {row['name'] for row in main_checks['check_runs']} == required
assert all(row['head_sha'] == merge['merge_commit'] for row in main_checks['check_runs'])
main_complete = all(row['status'] == 'completed' and row['conclusion'] == 'success' for row in main_checks['check_runs'])
files.extend(['merged-pr76.json', 'merge-tree-proof.json', 'pr76-head-checks.json', 'main-checks-435f4d0.json'])
record = {'head': gate['head'], 'pr': 'https://github.com/quuxio/oteleq/pull/76',
          'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'full_local_gate': 'passed', 'source_files_preserved': gate['source_files_after'],
          'regressions': {'capture': 171, 'generation': 963, 'rust': 74, 'node': 24, 'go': 4,
                          'distinct_total': 1236,
                          'nested_effect_and_observer_tests_are_not_counted_twice': True},
          'rust_product_line_coverage': 97.38, 'new_module_line_coverage': 100,
          'focused_tests_per_interpreter': 37, 'small_graph_oracle_pairs_per_interpreter': 500,
          'native_writer_processes': 4, 'interop_application_processes': 0, 'interop_sdk_processes': 0,
          'independent_review': 'clear', 'required_ci': 'passed', 'merged': True,
          'merge_commit': merge['merge_commit'], 'reviewed_tree_matches_merge': True,
          'post_merge_ci': 'passed' if main_complete else 'pending',
          'feature_delivery_complete': main_complete,
          'independent_review_sha256': hashlib.sha256(review_path.read_bytes()).hexdigest(),
          'rendered_readme_and_guide': 'checked on exact GitHub source revision',
          'authentic_origin_qualification': False, 'generated_prepared_python_admission': 'blocked',
          'project_goal_complete': False,
          'next': ('integrate authentic both-lane origin records and review the queued Java witness integration'
                   if main_complete else 'finish post-merge checks, then integrate authentic both-lane origin records'),
          'receipt_sha256': {name: hashlib.sha256((BASE / name).read_bytes()).hexdigest() for name in files}}
(BASE / 'CURRENT.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: record[key] for key in ('head', 'full_local_gate', 'source_files_preserved', 'independent_review', 'merged', 'project_goal_complete')}))
