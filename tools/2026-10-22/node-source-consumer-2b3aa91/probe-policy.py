"""Check the new consumer policy against the actual provisional public API."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-source-provider')
PROOF = Path(__file__).resolve().parent
HANDOFF = Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/handoff.json')
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import node_source

handoff = json.loads(HANDOFF.read_text())
root = Path(handoff['provider'])
node = Path(handoff['node_tools'][0]['node'])
tools = {'javascript': node, 'python-host': Path(handoff['python_tool']['path'])}
artefacts = node_source.artefacts(root, tools)
(PROOF / 'development-artefacts.json').write_text(json.dumps(artefacts, indent=2) + '\n')
environment = {'PATH': os.environ.get('PATH', ''), 'HOME': str(PROOF), 'TMPDIR': str(PROOF),
               'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'OTELC_NODE': str(node)}
results = []
for language, suffix in [('javascript', 'cjs'), ('typescript', 'mts')]:
    folder = PROOF / ('policy-probe-' + language)
    folder.mkdir(mode=0o700)
    entry = {'language': language, 'node_backend': node_source.SOURCE,
             'path': 'application/app.' + suffix, 'otelc_function': 'application.app.add'}
    requested = node_source.configuration(entry, 'http://127.0.0.1:4318', 'oteleq-source-probe')
    config = folder / 'policy.toml'
    config.write_text(node_source.policy(entry, 'http://127.0.0.1:4318', 'oteleq-source-probe'))
    argv = [*handoff['cli_prefix'], '--config', str(config), 'plan']
    result = subprocess.run(argv, cwd=root, env=environment, capture_output=True, timeout=30)
    (folder / 'stdout').write_bytes(result.stdout)
    (folder / 'stderr').write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    node_source.verify_capabilities(value, requested, language)
    results.append({'language': language, 'argv': argv, 'exit_code': result.returncode,
                    'response_sha256': hashlib.sha256(result.stdout).hexdigest(),
                    'implemented': value['implemented'], 'candidates': value['candidates']})
assert artefacts == node_source.artefacts(root, tools)
receipt = {'provider_head': handoff['head'], 'consumer_base': '5c5a38e',
           'consumer_component_sha256': hashlib.sha256((SOURCE / 'adapters/generation/node_source.py').read_bytes()).hexdigest(),
           'artefact_records': len(artefacts), 'results': results, 'application_launches': 0,
           'scope': 'actual policy and metadata development probe; not provider qualification', 'accepted': False}
(PROOF / 'policy-probe-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
