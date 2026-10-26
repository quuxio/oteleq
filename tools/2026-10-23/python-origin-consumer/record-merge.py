"""Verify the reviewed source tree was merged as quuxio before cleanup."""

import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-cpp-receivers')
HEAD = 'd4c663d0f6f86579dfa3ed3b326664db7406439e'
merged = json.loads((BASE / 'merged-pr76.json').read_text())
assert merged['merged'] and merged['merged_by']['login'] == 'quuxio' and merged['head']['sha'] == HEAD
commit = merged['merge_commit_sha']


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=REPO, text=True).strip()


assert git('rev-parse', commit + '^{tree}') == git('rev-parse', HEAD + '^{tree}')
record = {'reviewed_head': HEAD, 'merge_commit': commit, 'merged_by': merged['merged_by']['login'],
          'merged_at': merged['merged_at'], 'reviewed_tree': git('rev-parse', HEAD + '^{tree}'),
          'merged_tree': git('rev-parse', commit + '^{tree}'), 'exact_tree_match': True,
          'local_keeper_head': git('rev-parse', 'HEAD'), 'local_keeper_status': git('status', '--porcelain'),
          'commit_author': git('show', '--no-patch', '--format=%an <%ae>', commit),
          'project_goal_complete': False}
assert record['local_keeper_head'] == commit and not record['local_keeper_status']
(BASE / 'merge-tree-proof.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
