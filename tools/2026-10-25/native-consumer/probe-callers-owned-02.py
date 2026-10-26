"""Run automatically materialised compiler-bound callers through the held SDK."""
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

SOURCE=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-generated')
SDK=Path('/Users/sclarke/github/otelc-qualification/work/native-build-context')
INDEX=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/native-build-context/source-5476ce0.json').read_text())
ROOT=Path(__file__).resolve().parent/'caller-owned-probe-02';ROOT.mkdir(mode=0o700)
sys.path[:0]=[str(SOURCE/'adapters/generation'),str(SOURCE/'examples'),str(SOURCE/'tests'),str(SDK)]
import generation,native_prepared,native_sdk,native_session,native_telemetry,native_toolchain,native_unit_build,native_unit_caller,otelc_capture as capture,typed_capture
from otelc.config import Policy
import test_generation_native_workers as workers


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def facts(path):
    stat=path.stat()
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return [digest,stat.st_dev,stat.st_ino,stat.st_mode,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_nlink]
def config(path,data):
    lines=['schema_version=3','languages='+json.dumps(data['languages'])]
    for name,rows in data.items():
        if type(rows)is dict:lines+=['['+name+']',*[key+'='+json.dumps(value) for key,value in rows.items()]]
    path.write_text('\n'.join(lines)+'\n')
def execute(argv,cwd):return subprocess.run(list(map(str,argv)),cwd=cwd,env=environment,capture_output=True,timeout=120)

consumer=sorted(set(subprocess.check_output(['git','ls-files'],cwd=SOURCE,text=True).splitlines())|{'adapters/generation/native_unit_caller.py','tests/test_generation_native_callers.py'})
paths=[SOURCE/name for name in consumer]+[SDK/name for name in INDEX['files']]+[SDK/'build/context-sdk/native-sdk-build.json',SDK/'build/context-sdk/libotelc_native_runtime.dylib']
before={str(path):facts(path) for path in paths};write(ROOT/'inputs-before.json',before)
assert all(before[str(SDK/name)][0]==digest for name,digest in INDEX['files'].items())
state={'status':'running','dirty_development_snapshot':True,'consumer_base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip(),'sdk_head':INDEX['head'],'started':datetime.now(timezone.utc).isoformat(),'applications':[],'scope':'Automatic per-unit caller materialisation, independent compiler binding and actual owned SDK/plain execution. Public CLI integration and retained workflow qualification remain open.'}
write(ROOT/'status.json',state);started=time.monotonic()
environment={key:value for key,value in os.environ.items() if not key.startswith(('OTEL','OTELEQ','GH_','GITHUB_','SONAR_','AWS_'))}
llvm=Path('/opt/homebrew/opt/llvm@22/bin/llvm-config');environment.update(LLVM_CONFIG=str(llvm),PYTHONDONTWRITEBYTECODE='1')
os.environ.update(OTELC_CLANG=str(llvm.parent/'clang'),OTELC_CLANGXX=str(llvm.parent/'clang++'))
try:
    tools=native_toolchain.capture(llvm,llvm.parent/'clang++','cpp',ROOT,execute)
    sdk=native_sdk.capture(SDK,SDK/'build/context-sdk',tools,cmake=Path('/opt/homebrew/bin/cmake'),ninja=Path('/opt/homebrew/bin/ninja'))
    for language in ('c','cpp'):
        base=ROOT/language;base.mkdir()
        fixture=workers.NativeWorkersTests('test_c_real_target_captures_all_state_without_calling_application_memcpy')
        fixture.base=base;fixture.root=base/'original'
        for name in ('src','include','build'):(fixture.root/name).mkdir(parents=True)
        profile,entry,_=fixture.prepare(language,throws=language=='cpp')
        policy=Policy.parse({'schema_version':3,'languages':[language],'resource':{'service_name':'oteleq-native-callers'},
            'sources':{'include':['**']},'functions':{'include':['work::selected(short)' if language=='cpp' else 'selected']},
            'metrics':{'collection':True,'emission':True},'traces':{'enabled':True,'sample_ratio':1.0},
            'export':{'endpoint':'http://127.0.0.1:1','interval_ms':60000,'timeout_ms':1000,'shutdown_timeout_ms':5000}}).data
        source=native_unit_caller.freeze(sdk,fixture.project,profile,base/'evidence',entry,[5],policy)
        caller=native_unit_caller.prepare(source,base/'helpers',base/'caller-evidence',base/'compiled',execute)
        recipe=caller.intent.recipe();write(base/'recipe.json',recipe);config(base/'policy.toml',policy)
        argv=[sys.executable,'-I','-S','-B',SDK/'otelc/cli_bootstrap.py','--config',base/'policy.toml','native-build',
            '--language',language,'--root',fixture.project,'--recipe',base/'recipe.json','--output',caller.intent.output,'--sdk-build',sdk.directory]
        write(base/'build.command.json',list(map(str,argv)));result=execute(argv,base)
        (base/'build.stdout').write_bytes(result.stdout);(base/'build.stderr').write_bytes(result.stderr)
        assert result.returncode==0,result.stderr.decode(errors='replace')
        built=native_unit_build.read(caller.intent);caller.recheck(base/'after-build-inputs',execute)
        observations=[]
        for plain in (True,False):
            label='plain' if plain else 'woven'
            with capture.receiver() as (endpoint,bodies,errors):
                current=copy.deepcopy(policy);current['export']['endpoint']=endpoint
                policy_file=base/(label+'.toml');config(policy_file,current)
                expected=native_prepared.freeze(built,base/('runtime-'+label),Path(sys.executable).absolute(),policy_file,current,plain=plain)
                argv=[sys.executable,'-I','-S','-B',SDK/'otelc/cli_bootstrap.py','--config',policy_file,'native-run',
                    '--build',built.intent.output,'--runtime',expected.runtime,'--prepare-only']
                if plain:argv.append('--plain')
                prepared=execute(argv,base);(base/(label+'.prepare.stdout')).write_bytes(prepared.stdout);(base/(label+'.prepare.stderr')).write_bytes(prepared.stderr)
                assert prepared.returncode==0,prepared.stderr.decode(errors='replace')
                launch=native_prepared.read(expected);session=native_session.Session(launch);folder=base/('execution-'+label)
                observation=base/(label+'.observation')
                with native_session.retained(session):
                    result=generation.execute(native_prepared.command(expected),fixture.project,
                        env={**environment,'OTELEQ_OBSERVATION':str(observation)},folder=folder,timeout=30,record_process=True,interaction=session)
                assert result.returncode==0 and result.stdout==result.stderr==b'',(result.returncode,result.stdout,result.stderr)
                assert errors==[];capture.retain_http(folder,bodies,errors)
                name='src/one.'+('cpp::work::selected(short)' if language=='cpp' else 'c::selected')
                witness=native_telemetry.witness(session.execution,bodies,current['resource']['service_name'],(name,),folder=folder)
                observed=typed_capture.scalar_capture(observation.read_bytes(),entry);observations.append(observed)
                write(base/(label+'.typed.json'),observed)
                caller.recheck(base/('after-'+label+'-inputs'),execute)
                state['applications'].append({'language':language,'plain':plain,'pid':session.child,'supervisor_pid':session.started.owner.pid,'witness':witness})
        state[language+'_observations_equal']=observations[0]==observations[1]
        assert observations[0]==observations[1],language+' real application state differs; preserve and investigate'
    state['status']='passed'
except Exception as error:
    traceback.print_exc();state.update(status='failed',error=repr(error))
finally:
    after={str(path):facts(path) for path in paths};write(ROOT/'inputs-after.json',after);state['held_source_sdk_facts']=before==after
    if before!=after:state['status']='failed'
    state.update(seconds=round(time.monotonic()-started,3),finished=datetime.now(timezone.utc).isoformat());write(ROOT/'status.json',state);print(json.dumps(state,indent=2),flush=True)
    raise SystemExit(0 if state['status']=='passed' else 1)
