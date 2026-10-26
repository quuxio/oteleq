"""Preserve a setup-only audit failure and start a fresh development attempt."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
failure = {'status': 'failed_setup', 'error': "KeyError: SDK_INDEX['parent_head']", 'actual_applications': 0,
           'actual_sdk_processes': 0, 'scope': 'qualification harness metadata setup; no CLI or application launched'}
with (ROOT / 'public-development-01/status.json').open('x') as output:
    output.write(json.dumps(failure, indent=2) + '\n')
text = (ROOT / 'qualify-development-01.py').read_text()
assert text.count('SDK_INDEX["parent_head"]') == 1
text = text.replace('SDK_INDEX["parent_head"]', 'SDK_INDEX["head"]')
assert text.count('public-development-01') == 1
text = text.replace('public-development-01', 'public-development-02')
with (ROOT / 'qualify-development-02.py').open('x') as output:
    output.write(text)
