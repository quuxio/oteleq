"""Exercise the current public build-only API with independently pinned inputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SDK = ROOT.parent / 'go-http2-review-33d74f2/source'
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-provider')
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples')]
import go_build as build
import go_files as files

folder = ROOT / 'prototype-build3-03'
folder.mkdir(mode=0o700)
application = folder / 'application'
application.mkdir()
sentinel = folder / 'unexpected-application-start'
(application / 'go.mod').write_text('module example.com/oteleqfixture\n\ngo 1.26.0\n')
(application / 'main.go').write_text('package main\nimport("fmt";"os")\n'
    + 'func init(){os.WriteFile(' + json.dumps(str(sentinel)) + ',[]byte("unexpected startup"),0600)}\n'
    + 'func Add(value int)int{return value+1}\nfunc main(){fmt.Print(Add(21))}\n')
policy = folder / 'otelc.toml'
policy.write_bytes((ROOT / 'prototype-build-01/otelc.toml').read_bytes())
provider_index = json.loads((ROOT.parent / 'go-http2-review-33d74f2/source-index.json').read_text())
consumer_index = json.loads((ROOT / 'source-262457d.json').read_text())
before = {name: files.file(SDK / name)[:2] for name in provider_index['files']}
assert all(value[0]['sha256'] == provider_index['files'][name] for name,value in before.items())
assert all(hashlib.sha256((CONSUMER/name).read_bytes()).hexdigest() == digest for name,digest in consumer_index['files'].items())
original, sdk, context = files.freeze(application), files.freeze(SDK / 'adapters/go'), files.freeze(ROOT / 'prototype-build-01/bundle/context')
tools, _ = files.read(SDK / 'build/go-upstream/toolchain.json')
go = '/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
assert tools['go'] == go
build.verify_tools(tools,tools)
env = {k:v for k,v in os.environ.items() if not k.startswith(('OTEL','GH_','GITHUB_','SONAR_','AWS_'))}
python = ROOT.parent / 'python-live-metrics/env-312/bin/python'
env.update(OTELC_PYTHON=str(python),PATH=str(python.parent)+os.pathsep+str(Path(go).parent)+os.pathsep+env.get('PATH',''),
    GOPATH=str(ROOT.parent / 'go-http2-review-33d74f2/go-path'),
    GOMODCACHE=str(ROOT.parent / 'go-source-review-67b1b0d/source/build/go-module-cache'),
    GOCACHE=str(ROOT.parent / 'go-http-review-b58d798/go-cache'),
    GOTOOLCHAIN='local',GOWORK='off',GOFLAGS='',PYTHONDONTWRITEBYTECODE='1')
def query(name, argv):
    result = subprocess.run(argv,cwd=application,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    (folder/(name+'.stdout')).write_bytes(result.stdout)
    (folder/(name+'.stderr')).write_bytes(result.stderr)
    assert result.returncode == 0
    return result.stdout
settings = json.loads(query('settings',[go,'mod','edit','-json']))
raw = query('modules',[go,'list','-m','-mod=readonly','-json','all']).decode().strip()
modules=[]
while raw:
    value,end=json.JSONDecoder().raw_decode(raw);modules.append(value);raw=raw[end:].lstrip()
argv=[str(SDK/'bin/quux-otelc'),'--config',str(policy),'go-build','--root',str(application),'--output',str(folder/'bundle'),'--go',go]
(folder/'command.json').write_text(json.dumps({'argv':argv,'cwd':str(SDK),'provider':provider_index['head'],'consumer':consumer_index['head']},indent=2)+'\n')
started=time.monotonic()
with (folder/'stdout').open('xb') as out,(folder/'stderr').open('xb') as err:
    result=subprocess.run(argv,cwd=SDK,env=env,stdout=out,stderr=err,timeout=180)
assert result.returncode == 0,(folder/'stderr').read_text()[-2500:]
intent=build.Intent(folder/'bundle',original,sdk,'.',(build.Target('example.com/oteleqfixture.Add','main.go',4,1),),tools,settings,modules,context)
with patch('subprocess.run',side_effect=AssertionError('reader executed tool')),patch('subprocess.Popen',side_effect=AssertionError('reader started application')):
    actual=build.read(intent);actual.verify()
assert not sentinel.exists()
assert all(files.file(SDK/name)[:2] == value for name,value in before.items())
assert all(hashlib.sha256((CONSUMER/name).read_bytes()).hexdigest() == digest for name,digest in consumer_index['files'].items())
receipt={'result':'passed','seconds':round(time.monotonic()-started,3),'provider':provider_index['head'],'consumer':consumer_index['head'],
    'schema':actual.receipt['schema_version'],'runtime_protocols':actual.receipt['runtime_protocols'],'provider_files_bytes_and_facts_held':len(before),
    'consumer_files_bytes_held':len(consumer_index['files']),'original_inputs_held':len(original.identities),'commands':len(actual.receipt['commands']),
    'compiler_evidence_files_held':len(actual.evidence),'context_files_pinned_before_build':len(context.identities),
    'module_settings_and_graph_read_before_provider_build':True,'literal_init_sentinel_absent':True,'new_target_applications':0,
    'scope':'Authentic build3/config2/health4 component compatibility only. Caller tools/settings/modules/source frozen before public build. Expected context is the independently retained earlier build-only fixture, not a new independently reproduced profile. Private generated helper reproduction and actual owned generated execution remain open.'}
(folder/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
