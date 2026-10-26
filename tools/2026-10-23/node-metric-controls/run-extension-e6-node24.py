"""Exercise the new retained-route verifier against a completed development corpus."""
import json
import os
from pathlib import Path
import sys

root = Path(__file__).parent
source = root / 'source-5ae2b01'
sys.path.insert(0, str(source / 'tests'))
from node_controls_routes import retained_routes

cli = root / 'quux-oteleq-d5b45af'
os.environ.update(OTELEQ_CLI=str(cli), OTELEQ_PYTHON=sys.executable)
profile = root / 'controls-e6-node24/javascript-native'
qualified = json.loads((profile.parent / 'QUALIFICATION.json').read_bytes())['profiles'][0]
assert qualified['language'] == 'javascript'
result = retained_routes(cli, profile, Path(qualified['workspace']), profile / 'application/controls.cjs')
print(json.dumps({key: value for key, value in result.items() if key != 'application_identities'}))
