"""Inspect real compiler/module context without running an application initialiser."""

import hashlib
import json
from pathlib import Path
import sys

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-source-provider')
PROOF = Path(__file__).resolve().parent
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import generation
import node_project
import otelc_capture as capture

handoff = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/handoff.json').read_text())
provider = Path(handoff['provider'])
node = Path(handoff['node_tools'][0]['node'])
root = PROOF / 'module-context-initial'
root.mkdir(mode=0o700)
components = {name: hashlib.sha256((SOURCE / 'adapters/generation' / name).read_bytes()).hexdigest()
              for name in ('node_context.mjs', 'node_source_context.mjs', 'node_source_context.py', 'node_project.py')}
(root / 'source-before.json').write_text(json.dumps(components, indent=2) + '\n')
results = []
for backend, suffix, expected in [('native', 'cts', 'commonjs'), ('api', 'mts', 'module')]:
    case = root / backend
    case.mkdir(mode=0o700)
    project = case / 'project'
    project.mkdir(mode=0o700)
    source = project / ('app.' + suffix)
    text = 'throw new Error("APPLICATION_INITIALISER_EXECUTED");\nfunction add(value:number):number {return value+1;}\n'
    source.write_text(text)
    environment = capture.environment(project, {'javascript': node}, 'metadata-only', provider)
    environment['TMPDIR'] = str(case)

    def execute(command, cwd, input_data=None, *, max_output_bytes=None):
        return generation.execute(command, cwd, environment, case / 'process', input_data=input_data,
                                  max_output_bytes=max_output_bytes, timeout=60, record_process=True)

    result = node_project.context(source, project, 'typescript', provider, node, execute,
                                  source_backend=backend, evidence=case / 'compiler')
    assert result['format'] == expected and result['source_compiler']['compiler']['backend'] == backend
    assert source.read_text() == text
    assert not (case / 'compiler/node-launch.json').exists()
    results.append({'backend': backend, 'format': result['format'], 'node_version': result['node_version']})
assert components == {name: hashlib.sha256((SOURCE / 'adapters/generation' / name).read_bytes()).hexdigest()
                      for name in components}
receipt = {'provider_head': handoff['head'], 'components': components, 'results': results,
           'metadata_processes': 2, 'application_launches': 0,
           'scope': 'actual native/API compiler and Node loader inspection; initialisers replaced before evaluation',
           'accepted_provider': False}
(root / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
