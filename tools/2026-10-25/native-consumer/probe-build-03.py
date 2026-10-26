"""Compile via the public SDK and check the independent consumer build reader."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-public-provider')
SDK = Path('/Users/sclarke/github/otelc-qualification/work/native-prepared')
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-prepared/source-4a85c18.json').read_text())
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import native_build
import native_sdk
import native_toolchain
import native_prepared
import native_protocol

ROOT = Path(__file__).resolve().parent / 'build-probe-03'; ROOT.mkdir(mode=0o700)
PROJECT = ROOT / 'application'; PROJECT.mkdir()
(PROJECT / 'main.cpp').write_text('__attribute__((noinline)) int workload(int x){return x+7;}\nint main(){return workload(10)==17?0:1;}\n')
POLICY = {'schema_version': 3, 'languages': ['cpp'], 'resource': {'service_name': 'oteleq-native-component'},
 'export': {'endpoint': 'http://127.0.0.1:1', 'interval_ms': 1000, 'timeout_ms': 1000, 'shutdown_timeout_ms': 5000},
 'sources': {'include': ['main.cpp'], 'exclude': []}, 'functions': {'include': ['main.cpp::workload(int)'], 'exclude': []},
 'metrics': {'collection': True, 'emission': True, 'histogram_boundaries_seconds': [1e-6, 1e-5, .0001, .001, .01, .1, 1.]},
 'traces': {'enabled': True, 'sample_ratio': 1.0},
 'lifetimes': {'enabled': False, 'include': [], 'exclude': [], 'max_live': 4096, 'release_methods': ['close']},
 'context': {'tasks': False, 'http': False}, 'benchmark': {'iterations': 10000, 'samples': 15, 'warmup': 5}}
lines = ['schema_version=3', 'languages=["cpp"]']
for key, value in POLICY.items():
 if type(value) is dict:
  lines += ['['+key+']', *[name+'='+json.dumps(item) for name,item in value.items()]]
config=ROOT/'policy.toml'; config.write_text('\n'.join(lines)+'\n')

def facts(path):
 info=path.stat()
 return [hashlib.sha256(path.read_bytes()).hexdigest(),info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns]
def inputs():
 return {'sdk':{name:facts(SDK/name) for name in INDEX['files']},
         'consumer':{name:facts(SOURCE/'adapters/generation'/name) for name in ('native_protocol.py','native_inputs.py','native_toolchain.py','native_sdk.py','native_build.py','native_prepared.py')},
         'application':{name:facts(PROJECT/name) for name in ('main.cpp',)}}
def write(name,value):
 (ROOT/name).write_text(json.dumps(value,indent=2)+'\n')

before=inputs();write('inputs-before.json',before)
assert all(before['sdk'][name][0]==sha for name,sha in INDEX['files'].items())
state={'status':'running','dirty_development_snapshot':True,'sdk_head':INDEX.get('head'),'applications_launched':0,
       'started':datetime.now(timezone.utc).isoformat()};write('status.json',state)
started=time.monotonic()
try:
 def execute(argv,cwd):
  return subprocess.run(list(map(str,argv)),cwd=cwd,capture_output=True,timeout=10,check=False)
 llvm=Path('/opt/homebrew/opt/llvm@22/bin/llvm-config')
 tools=native_toolchain.capture(llvm,llvm.parent/'clang++','cpp',ROOT,execute)
 sdk=native_sdk.capture(SDK,SDK/'build/prepared-sdk',tools,cmake=Path('/opt/homebrew/bin/cmake'),ninja=Path('/opt/homebrew/bin/ninja'))
 intent=native_build.freeze(sdk,PROJECT,ROOT/'build','cpp',('main.cpp',),((PROJECT/'main.cpp',),),POLICY)
 env={k:v for k,v in os.environ.items() if not k.startswith(('OTEL','OTELEQ','GH_','GITHUB_','SONAR_','AWS_'))}
 env.update(LLVM_CONFIG=str(llvm),PYTHONDONTWRITEBYTECODE='1')
 command=[sys.executable,'-I','-S','-B',str(SDK/'otelc/cli_bootstrap.py'),'--config',str(config),'native-build',
          '--language','cpp','--root',str(PROJECT),'--source','main.cpp','--output',str(intent.output),'--sdk-build',str(sdk.directory)]
 write('command.json',{'argv':command,'cwd':str(ROOT)})
 process=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,timeout=300)
 (ROOT/'build.stdout').write_bytes(process.stdout);(ROOT/'build.stderr').write_bytes(process.stderr)
 state['producer_exit_code']=process.returncode
 assert process.returncode==0,process.stderr.decode(errors='replace')
 built=native_build.read(intent)
 assert json.loads(process.stdout)==built.manifest()
 built.verify()

 preparations=[]
 for plain in (True,False):
  runtime=ROOT/('runtime-plain' if plain else 'runtime-woven')
  arguments=('literal space','--literal','$literal')
  expected=native_prepared.freeze(built,runtime,Path(sys.executable).absolute(),config,POLICY,plain=plain,arguments=arguments)
  argv=[sys.executable,'-I','-S','-B',str(SDK/'otelc/cli_bootstrap.py'),'--config',str(config),
        'native-run','--build',str(built.intent.output),'--runtime',str(runtime),'--prepare-only']
  if plain:argv.append('--plain')
  argv+=['--',*arguments]
  completed=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,timeout=30)
  label='prepare-plain' if plain else 'prepare-woven'
  (ROOT/(label+'.stdout')).write_bytes(completed.stdout);(ROOT/(label+'.stderr')).write_bytes(completed.stderr)
  write(label+'.command.json',{'argv':argv,'exit_code':completed.returncode})
  assert completed.returncode==0,completed.stderr.decode(errors='replace')
  value=native_prepared.read(expected)
  assert json.loads(completed.stdout)==value.value(native_prepared.PREPARED)
  value.verify()
  assert {p.name for p in runtime.iterdir()}=={native_prepared.REQUEST,native_prepared.PLAN,native_prepared.PREPARED}
  preparations.append({'plain':plain,'runtime':str(runtime),'command':native_prepared.command(expected),
                       'arguments':value.value(native_prepared.REQUEST)['arguments']})
 state['preparations']=preparations
 state.update(status='passed',retained_build_files=len(built.files),llvm_version=tools.version,
              original_sdk_sources=len(sdk.sources),query_channels=[{'argv':q.command,'stdout':q.stdout} for q in tools.queries],
              compiled_application_lanes=2,sdk_library_sha256=sdk.library.sha256)
except Exception as error:
 state.update(status='failed',error=repr(error))
finally:
 after=inputs();write('inputs-after.json',after)
 state['preservation']={name:before[name]==after[name] for name in before}
 if not all(state['preservation'].values()):state['status']='failed'
 state.update(seconds=round(time.monotonic()-started,3),finished=datetime.now(timezone.utc).isoformat())
 write('status.json',state);print(json.dumps(state,indent=2),flush=True)
 raise SystemExit(0 if state['status']=='passed' else 1)
