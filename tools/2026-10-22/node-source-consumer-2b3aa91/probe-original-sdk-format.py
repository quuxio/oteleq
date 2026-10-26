"""Run original TypeScript sources through the public SDK plain recipe, without callers."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

BASE=Path(__file__).resolve().parent
FROZEN=BASE/'public-context-matrix-initial/source'
sys.path[:0]=[str(FROZEN/'adapters/generation'),str(FROZEN/'examples')]
import generation
import node_source
import node_launch

SDK=Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/provider')
NODE='/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
ROOT=BASE/sys.argv[1];ROOT.mkdir(mode=0o700)
rows=[]
for compiler in ('native','api'):
 folder=ROOT/compiler;folder.mkdir();project=folder/'project';project.mkdir()
 original=BASE/'public-context-matrix-initial'/(compiler+'-ts-default')/'application/sample.ts'
 source=project/'sample.ts';shutil.copyfile(original,source);digest=hashlib.sha256(source.read_bytes()).hexdigest()
 entry={'language':'typescript','path':'sample.ts','otelc_function':'sample.selected','node_backend':'source-v1'}
 policy=folder/'policy.toml';policy.write_text(node_source.policy(entry,'http://127.0.0.1:4318','original-format-probe'))
 request={'schema_version':1,'provider':str(SDK),'project':str(project),'entry':str(source),'runtime':str(folder/'runtime'),'policy':str(policy),'node':NODE,'language':'typescript','compiler':compiler,'plain':True,'gc_fixture':False,'timeout_ms':60000}
 (folder/'request.json').write_text(json.dumps(request)+'\n')
 bootstrap="import runpy,sys;sys.path[:0]=[sys.argv.pop(1),sys.argv.pop(1)];runpy.run_module('node_source_worker',run_name='__main__')"
 command=[SDK/'.venv/bin/python','-I','-B','-c',bootstrap,FROZEN/'adapters/generation',FROZEN/'examples',folder/'request.json']
 env={'PATH':'/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin','HOME':str(folder),'TMPDIR':str(folder),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
 result=generation.execute(command,project,env,folder,timeout=60,record_process=True)
 assert result.returncode==0 and result.stderr==b''
 assert hashlib.sha256(source.read_bytes()).hexdigest()==digest==hashlib.sha256(original.read_bytes()).hexdigest()
 records=json.loads((folder/'runtime/node-plain-inputs.json').read_bytes())
 row={'compiler':compiler,'source_sha256':digest,'original_without_caller':True,'returncode':result.returncode,'stdout':result.stdout.decode(),'recorded_compiled_formats':[r['format'] for r in records['loaded_inputs'] if r['kind']=='compiled'],'actual_application':json.loads((folder/'node-source-application.json').read_bytes()),'accepted':False}
 rows.append(row);(ROOT/'receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
