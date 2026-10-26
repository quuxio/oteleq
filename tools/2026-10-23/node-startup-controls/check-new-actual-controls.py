from pathlib import Path
import json,sys
root=Path(__file__).parent
source=root/'source-c9fef1f'
sys.path.insert(0,str(source/'tests'))
from node_controls_routes import receipt_controls
profile=Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/node-metric-controls/controls-a295-node24/javascript-native')
progress=json.loads((profile.parent/'QUALIFICATION.json').read_bytes())
workspace=Path(progress['profiles'][0]['workspace'])
folder=root/'new-control-development-recheck';folder.mkdir()
count=receipt_controls(profile,workspace,folder)
assert count==14
record={'actual_evidence_refusals':count,'new_application_launches':0,'executor':'a295b0e0147e481e7950691589fc17e5f5afb8d2','verifier':'c9fef1fa5ab446a628a52647266e8774fdb48da8','scope':'Development recheck of old Node24 JavaScript positive-first actual receipts; not startup-off execution or admission'}
(folder/'RECHECK.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
