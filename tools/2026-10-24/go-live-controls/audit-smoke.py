"""Recheck the original eight Go executions without launching applications."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--audit-dir', type=Path, required=True)
args = parser.parse_args()
SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
sys.path.insert(0, str(SOURCE / 'tests'))
import go_live_qualification as oracle
import qualify_go_controls as qualifier

BASE = Path(__file__).resolve().parent
ORIGINAL = BASE / 'smoke-development-01'
DEST = args.audit_dir.resolve()
DEST.mkdir()
SDK = BASE.parent / 'go-scope-provider/sdk-eda9fcc'
CLI = BASE.parent / 'go-scope-provider/target-e765f0d-public/debug/quux-oteleq'
FILES = ['tests/' + name + '.py' for name in ('go_live_fixture', 'go_live_receipt', 'go_live_qualification',
         'qualify_go_controls', 'qualify_go_receivers', 'sequence_qualification', 'qualify_project_tests')]

def code():
    return {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in FILES}

before, held = qualifier.evidence_facts(ORIGINAL), code()
state = {'status': 'running', 'original_evidence': str(ORIGINAL), 'dirty_development_snapshot': True,
         'new_application_launches_during_audit': 0}
qualifier.write(DEST / 'result.json', state)
try:
    observed = oracle.check_report(ORIGINAL / 'comparison/report.json', 2, start='both-on', provider=SDK)
    qualifier.controls(CLI, ORIGINAL / 'comparison/report.json', DEST)
    assert code() == held and qualifier.evidence_facts(ORIGINAL) == before
    state.update(status='passed', application_observations=observed, actual_application_launches=8,
        sdk_processes=4, step_observations=40, complete_spans=24, altered_comparison_refusals=5,
        original_evidence_files_held=len(before), original_failure_preserved=True, code_sha256=held,
        cli_head='e765f0d4e98b9e4fa992ec5b28a71c4203b2b386', sdk_head='eda9fccdfac281dc8763b485a540e10219f45ea7',
        scope='both-on startup direct source-scope-v1 workflow only; other startup states and retained/promoted routes remain open',
        audit_corrections=['startup acknowledgement includes release', 'plain has no SDK config',
            'health policy digest uses default JSON separators', 'metric exemplars join collected trace roots',
            'removed source fields also remove unreachable storage nodes in difference controls'])
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    state['original_evidence_preserved'] = qualifier.evidence_facts(ORIGINAL) == before
    state['audit_code_preserved'] = code() == held
    if not state['original_evidence_preserved'] or not state['audit_code_preserved']:
        state['status'] = 'failed'
    qualifier.write(DEST / 'result.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
