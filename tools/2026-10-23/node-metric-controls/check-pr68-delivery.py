"""Check exact-head protected delivery state without changing GitHub."""
import json,os
from pathlib import Path
import subprocess

root=Path(__file__).parent
head='d2543a8c57b2cc2f0cec9a344b2ffdb1ce0e5fa0'
wrapper=['/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider/.venv/bin/python','/Users/sclarke/github/oteleq-qualification/2026-10-20/pause-for-reboot/quux-oteleq-gh.py']
env={**os.environ,'XDG_CACHE_HOME':'/Users/sclarke/github/oteleq-qualification/work/gh-cache'}
def api(path):
 return json.loads(subprocess.check_output([*wrapper,'api',path],env=env,text=True))
pr=api('repos/quuxio/oteleq/pulls/68')
assert pr['head']['sha']==head and pr['state']=='open'
checks=api('repos/quuxio/oteleq/commits/'+head+'/check-runs')['check_runs']
required={'Documentation and design examples':15368,'Rust comparator and 80% product coverage':15368,'SonarCloud Code Analysis':12526}
selected=[]
for name,application in required.items():
 rows=[row for row in checks if row['name']==name and row['app']['id']==application and row['head_sha']==head]
 assert rows,(name,'required app-bound check missing')
 row=max(rows,key=lambda row:row['id'])
 selected.append({'name':name,'head_sha':row['head_sha'],'app':row['app']['id'],'status':row['status'],'conclusion':row['conclusion']})
gate=json.loads((root/'gate-d2543a8.json').read_bytes())
rules=api('repos/quuxio/oteleq/rulesets/24784844')
assert rules['enforcement']=='active'
rule=next(row for row in rules['rules'] if row['type']=='required_status_checks')
assert rule['parameters']['strict_required_status_checks_policy'] is True
assert {(row['context'],row['integration_id']) for row in rule['parameters']['required_status_checks']}==set(required.items())
repo=api('repos/quuxio/oteleq')
record={'head':head,'draft':pr['draft'],'mergeable':pr['mergeable'],'mergeable_state':pr['mergeable_state'],'base':pr['base']['sha'],'local_gate_exit':gate.get('exit_code'),'checks':selected,'ruleset':rules['id'],'strict':True,'allow_merge_commit':repo['allow_merge_commit'],'allow_squash_merge':repo['allow_squash_merge']}
(root/'delivery-precheck-d2543a8.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record),flush=True)
