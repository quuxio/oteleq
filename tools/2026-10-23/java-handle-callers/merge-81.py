"""Merge only the independently reviewed exact head through normal protection."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
HEAD = 'dcf5ff4321531162e20a04740159fb072ad8fd3e'
WRAPPER = ['/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider/.venv/bin/python',
           '/Users/sclarke/github/oteleq-qualification/2026-10-20/pause-for-reboot/quux-oteleq-gh.py']
ENV = {**os.environ, 'XDG_CACHE_HOME': '/Users/sclarke/github/oteleq-qualification/work/gh-cache'}


def gh(*args):
    return subprocess.check_output([*WRAPPER, *args], cwd=ROOT, env=ENV, text=True)


value = json.loads(gh('pr', 'view', '81', '--repo', 'quuxio/oteleq', '--json',
                     'number,headRefOid,baseRefName,author,isDraft,state,mergeStateStatus,statusCheckRollup'))
assert value['headRefOid'] == HEAD and value['baseRefName'] == 'main'
assert value['author']['login'] == 'quuxio' and value['state'] == 'OPEN' and value['isDraft'] is False
assert value['mergeStateStatus'] == 'CLEAN', value['mergeStateStatus']
required = {'Documentation and design examples', 'Rust comparator and 80% product coverage', 'SonarCloud Code Analysis'}
checks = {item['name']: item for item in value['statusCheckRollup']}
assert all(name in checks and checks[name]['status'] == 'COMPLETED'
           and checks[name]['conclusion'] == 'SUCCESS' for name in required)
gate = json.loads((ROOT / 'gate-dcf5ff4.json').read_text())
review = json.loads((ROOT / 'independent-review-dcf5ff4.json').read_text())
assert gate['head'] == HEAD and gate['exit_code'] == 0 and gate['source_preserved']
assert review['head'] == HEAD and review['verdict'] == 'clear_source_component' and not review['findings']
protection = json.loads(gh('api', 'repos/quuxio/oteleq/rulesets/24784844'))
assert protection == json.loads((ROOT / 'protection-before-dcf5ff4.json').read_text())
(ROOT / 'merge-preflight-dcf5ff4.json').write_text(json.dumps(value, indent=2) + '\n')
print(gh('pr', 'merge', '81', '--repo', 'quuxio/oteleq', '--squash', '--match-head-commit', HEAD, '--delete-branch'))
merged = json.loads(gh('pr', 'view', '81', '--repo', 'quuxio/oteleq', '--json',
                      'state,headRefOid,mergeCommit,mergedBy,mergedAt,url'))
assert merged['state'] == 'MERGED' and merged['headRefOid'] == HEAD and merged['mergedBy']['login'] == 'quuxio'
commit = json.loads(gh('api', 'repos/quuxio/oteleq/commits/' + merged['mergeCommit']['oid']))
tree = subprocess.check_output(['git', 'rev-parse', HEAD + '^{tree}'],
                              cwd='/Users/sclarke/github/oteleq-qualification/work/oteleq-java-handle-callers', text=True).strip()
assert commit['commit']['tree']['sha'] == tree and commit['author']['login'] == 'quuxio'
assert json.loads(gh('api', 'repos/quuxio/oteleq/rulesets/24784844')) == protection
record = {'reviewed_head': HEAD, 'merge_commit': merged['mergeCommit']['oid'],
          'reviewed_tree': tree, 'merged_tree': commit['commit']['tree']['sha'],
          'exact_reviewed_merge_tree': True, 'pr': 81, 'merged_by': 'quuxio',
          'merged_at': merged['mergedAt'], 'required_pr_checks': 'all_success',
          'main_checks': 'pending', 'protection_unchanged': True,
          'independent_review_sha256': hashlib.sha256((ROOT / 'independent-review-dcf5ff4.json').read_bytes()).hexdigest()}
(ROOT / 'DELIVERY.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
