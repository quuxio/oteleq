"""Account for every remaining remote branch and open PR after delivery."""

import datetime
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent
pages = json.loads((BASE / 'open-pr-pages.json').read_text())
branch_pages = json.loads((BASE / 'branch-pages.json').read_text())
prs = [row for page in pages for row in page]
branches = [row for page in branch_pages for row in page]
assert len({row['number'] for row in prs}) == len(prs)
assert len({row['name'] for row in branches}) == len(branches)
assert not prs and {row['name'] for row in branches} == {'main', 'traffic-badges'}
clones = []
for repo in ('/Users/sclarke/github/oteleq', '/Users/sclarke/github/oteleq-qualification/work/oteleq-cpp-receivers'):
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    upstream = subprocess.check_output(['git', 'rev-parse', '@{upstream}'], cwd=repo, text=True).strip()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=repo, text=True).strip()
    assert not status and branch == 'main' and head == upstream == '435f4d0a7aabe4c0e57d3de31d407905871840b3'
    clones.append({'path': repo, 'head': head, 'branch': branch, 'clean': True, 'matches_upstream': True})
feature = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-origin-reader')
assert not feature.exists()
record = {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'open_pr_count': len(prs),
          'remote_branches': [{'name': row['name'], 'head': row['commit']['sha']} for row in branches],
          'pr_pages': len(pages), 'branch_pages': len(branch_pages), 'all_ids_unique': True,
          'clones': clones, 'completed_feature_worktree_removed': True,
          'intentional_artifact_branch': 'traffic-badges', 'project_goal_complete': False}
(BASE / 'HYGIENE.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'open_pr_count': len(prs), 'remote_branches': [row['name'] for row in branches],
                  'clean_main_clones': len(clones), 'completed_feature_worktree_removed': True}))
