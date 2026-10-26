"""Retain actual scalar reductions and frozen suite/replay for each source compiler."""
import json
import os
from pathlib import Path
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE/'public-receiver-initial'
sys.path.insert(0,str(ROOT/'source/tests'))
import qualify_node_receivers as q
CLI=ROOT/'quux-oteleq'
PYTHON=Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/provider/.venv/bin/python')
os.environ['OTELEQ_CLI']=str(CLI);os.environ['OTELEQ_PYTHON']=str(PYTHON);os.environ['PYTHONDONTWRITEBYTECODE']='1'
rows=[]
for record in json.loads((ROOT/'receipt.json').read_bytes()):
 assert record['status']=='complete'
 folder=ROOT/(record['language']+'-'+record['compiler'])
 workspace=Path(record['workspace'])
 report=json.loads((folder/'comparison/report.json').read_bytes())
 case=next(c for c in report['cases'] if c['function'].endswith('.silent'))['case']
 reduction=folder/'reduction-routes'
 row={'language':record['language'],'compiler':record['compiler'],'accepted':False,'status':'running'};rows.append(row)
 (ROOT/'reduction-receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
 q.command([CLI,'shrink','--workspace',workspace,'--case',case,'--report-dir',reduction,'--trials','16'],folder,'source-reduction',expected=1)
 shrink=json.loads((reduction/'shrink.json').read_bytes());assert shrink['reduced_arguments']==[0.0] and shrink['status']=='candidate_rule_minimal'
 for f in [reduction/'original/report.json',reduction/'confirmation/report.json',*(Path(t['report']) for t in shrink['trials'])]:q.check_report(f,1)
 suite=Path(shrink['workspace']);q.framework(suite,folder,'source-reduced-framework',1)
 replay=json.loads(q.command([CLI,'replay','--workspace',suite,'--case',case],folder,'source-reduced-replay',expected=1));q.check_report(Path(replay['report']),1)
 plan=json.loads((suite/'plan.json').read_bytes());assert 'node_provider_manifest' in plan and (suite/'node-source-provider').is_dir()
 row.update(status='complete',reduced_arguments=shrink['reduced_arguments'],trials=len(shrink['trials']),actual_reduction_applications=len(list(reduction.rglob('node-source-application.json'))),frozen_framework_and_replay_applications=len(list((suite/'runs').rglob('node-source-application.json'))))
 (ROOT/'reduction-receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
