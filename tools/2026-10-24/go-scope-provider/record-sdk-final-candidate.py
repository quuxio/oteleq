"""Refresh the active checkpoint with the SDK's frozen review-fix candidate."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
path = ROOT / 'checkpoint.json'
state = json.loads(path.read_text())
state['github']['pr_body'] = 'pr-body-e765f0d-verified.md; uploaded successfully'
state['native_public_review']['supplemental_candidate'] = {
    'head': '4a85c180124b0d8dbfe2a4fcda254dc50e270200', 'files': 446, 'delta_from3c': 5,
    'archive_index': '/Users/sclarke/github/otelc-qualification/2026-10-24/native-prepared/source-4a85c18.json',
    'archive_sha256': '1f9ced5ad29a2a547a3ac2d384fe30be74ce4cee3c8dfb8e344ebc967fd7c9e3',
    'reported_tests': {'python312': {'tests': 13, 'seconds': 39.483}, 'python314': {'tests': 13, 'seconds': 44.858}},
    'status': 'SDK owner reports all3 findings fixed with before-fix regressions; root exact-delta review and independent real public API execution still required',
    'full_gate': 'queued after historical3c and corrected2481 gates terminate; not passing evidence',
    'reuse_request': 'asked owner for an immutable matching source tree and its SDK product; never re-root metadata or monkeypatch ROOT to consume a different build'}
state['native_public_review']['sdk_owner_action'] = 'all3 findings reproduced/fixed in frozen4a85c18; root review and full gates remain pending'
state['source_profile_remaining'] = [
    'The new source-scope single-call retained corpora are running: poll1414 and62773',
    'Maintain and qualify live all-startup generated/framework/export/replay/shrink/promotion routes with a restored intermediate mutation control',
    'Profile repeated matched-pair compilation after the corpora finish; consider retained build reuse only with held source/SDK/caller identities, fresh processes/fixtures and truthful unchanged metadata paths'
]
path.write_text(json.dumps(state, indent=2) + '\n')
print(json.dumps({'head': state['head'], 'goal_status': state['goal_status'], 'native_candidate': state['native_public_review']['supplemental_candidate']['head']}))
