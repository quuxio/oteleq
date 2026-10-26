"""Close the delivered slice while preserving the full project objective."""

import datetime
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
state = json.loads((BASE / 'CURRENT.json').read_text())
before = json.loads((BASE / 'main-ruleset-before.json').read_text())
after = json.loads((BASE / 'main-ruleset-after.json').read_text())
hygiene = json.loads((BASE / 'HYGIENE.json').read_text())
assert state['feature_delivery_complete'] and state['post_merge_ci'] == 'passed'
assert state['merge_commit'] == '435f4d0a7aabe4c0e57d3de31d407905871840b3'
assert before['id'] == after['id'] == 24784844
assert before['rules'] == after['rules'] and after['enforcement'] == 'active' and not after['bypass_actors']
assert hygiene['open_pr_count'] == 0 and len(hygiene['clones']) == 2
assert {row['name'] for row in hygiene['remote_branches']} == {'main', 'traffic-badges'}
files = ['CURRENT.json', 'HYGIENE.json', 'merge-tree-proof.json', 'main-checks-435f4d0.json',
         'main-ruleset-after.json', 'pr76-head-checks.json', 'merged-pr76.json']
record = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'pr': state['pr'], 'reviewed_head': state['head'], 'merge_commit': state['merge_commit'],
          'feature_delivery_complete': True, 'source_preserved': True, 'exact_reviewed_merge_tree': True,
          'required_pr_and_main_checks': 'passed', 'protected_normal_merge_as': 'quuxio',
          'protection_unchanged': True, 'open_pr_count': 0, 'clean_synced_main_clones': 2,
          'completed_feature_worktree_and_branch_removed': True,
          'authentic_origin_qualification': False, 'generated_prepared_python_admission': 'blocked',
          'project_goal_complete': False, 'completion_plan_rows_retained': 21,
          'next': state['next'],
          'receipt_sha256': {name: hashlib.sha256((BASE / name).read_bytes()).hexdigest() for name in files}}
(BASE / 'DELIVERY.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: record[key] for key in ('pr', 'merge_commit', 'feature_delivery_complete', 'required_pr_and_main_checks', 'open_pr_count', 'project_goal_complete')}))
