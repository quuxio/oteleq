"""Exercise caller-frozen build3 through the actual corrected SDK and OS gate."""
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import traceback

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/native-consumer/source-7f2f8cc')
SDK = Path('/Users/sclarke/github/otelc-qualification/work/native-build-context')
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/native-build-context/source-5476ce0.json').read_text())
ROOT = Path(__file__).resolve().parent / 'unit-build-probe-02'
ROOT.mkdir(mode=0o700)
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples'), str(SDK)]
import generation
import native_prepared
import native_protocol
import native_sdk
import native_session
import native_telemetry
import native_toolchain
import native_unit_build
import otelc_capture as capture
from otelc.config import Policy


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    info = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink]


CONSUMER_INDEX = json.loads((Path(__file__).resolve().parent / 'source-7f2f8cc.json').read_text())
consumer = sorted(CONSUMER_INDEX['files'])
held_paths = [SDK / name for name in INDEX['files']]
held_paths += [SDK / 'build/context-sdk/native-sdk-build.json', SDK / 'build/context-sdk/libotelc_native_runtime.dylib']
held_paths += [SOURCE / name for name in consumer]
before = {str(path): facts(path) for path in held_paths}
assert all(before[str(SDK / name)][0] == digest for name, digest in INDEX['files'].items())
write(ROOT / 'inputs-before.json', before)
state = {'status': 'running', 'dirty_development_snapshot': False, 'consumer_head': CONSUMER_INDEX['head'], 'sdk_head': INDEX['head'],
         'started': datetime.now(timezone.utc).isoformat(), 'applications': [],
         'scope': 'Exact consumer7f2f8cc; two explicit C/C++ per-unit builds and actual owned plain/woven applications. Not generated workflow qualification or SDK rebuild.'}
write(ROOT / 'status.json', state)
started = time.monotonic()
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL','OTELEQ','GH_','GITHUB_','SONAR_','AWS_'))}
llvm = Path('/opt/homebrew/opt/llvm@22/bin/llvm-config')
environment.update(LLVM_CONFIG=str(llvm), PYTHONDONTWRITEBYTECODE='1')


def execute(argv, cwd):
    return subprocess.run(list(map(str, argv)), cwd=cwd, env=environment, capture_output=True, timeout=30)


def config(path, policy):
    lines = ['schema_version=3', 'languages=' + json.dumps(policy['languages'])]
    for name, values in policy.items():
        if type(values) is dict:
            lines += ['[' + name + ']', *[key + '=' + json.dumps(value) for key,value in values.items()]]
    path.write_text('\n'.join(lines) + '\n')


try:
    descriptor = execute([sys.executable, '-I', '-S', '-B', SDK / 'otelc/cli_bootstrap.py',
                          'native-protocols', '--build-version', '3'], ROOT)
    assert descriptor.returncode == 0, descriptor.stderr
    native_protocol.verify_protocols(json.loads(descriptor.stdout), build_version=3)
    write(ROOT / 'protocols.json', json.loads(descriptor.stdout))
    tools = native_toolchain.capture(llvm, llvm.parent / 'clang++', 'cpp', ROOT, execute)
    sdk = native_sdk.capture(SDK, SDK / 'build/context-sdk', tools,
        cmake=Path('/opt/homebrew/bin/cmake'), ninja=Path('/opt/homebrew/bin/ninja'))
    for language in ('c', 'cpp'):
        base = ROOT / language; base.mkdir()
        project = base / 'application'; project.mkdir()
        headers = project / 'include'; headers.mkdir()
        header = headers / 'value.h'; header.write_text('#define BASE 11\n')
        other = project / 'entry'; other.mkdir()
        main = other / 'main.c'; main.write_text('int state=OFFSET;int main(void){return 0;}\n')
        work = project / ('work.cpp' if language == 'cpp' else 'work.c')
        work.write_text('#include <value.h>\nextern int state;\n__attribute__((noinline)) int work(int x){'
            + ('if(x<0)throw 17;' if language == 'cpp' else '') + 'state+=x;return state+BASE;}\n')
        private = base / 'private'; private.mkdir()
        augmented = private / ('observed.cpp' if language == 'cpp' else 'observed.c')
        augmented.write_bytes(work.read_bytes() + b'__attribute__((no_profile_instrument_function)) int observed_state(void){return state;}\n')
        overlay = private / 'overlay.json'
        write(overlay, {'version':0,'use-external-names':False,'roots':[
            {'type':'file','name':str(work),'external-contents':str(augmented)}]})
        driver = private / ('driver.cpp' if language == 'cpp' else 'driver.c')
        driver.write_text(('extern "C" ' if language == 'cpp' else 'extern ') + 'int printf(const char*,...);\n'
            'int work(int);int observed_state(void);int main(void){int a=observed_state();int b=work(2);int c=observed_state();'
            + ('int error=0;try{work(-1);}catch(int value){error=value;}printf("%d|%d|%d|%d\\n",a,b,c,error);'
               if language == 'cpp' else 'printf("%d|%d|%d\\n",a,b,c);') + 'return 0;}\n')
        recipe = {'schema_version':1,'kind':'otelc.native.unit-recipe','assets':list(map(str,(driver,augmented,overlay))),
            'units':[{'id':'work','role':'application','language':language,'source':str(work),'directory':str(project),
                'flags':['-std=c++20' if language=='cpp' else '-std=c11','-O1','-isystem',str(headers)],
                'overlay':str(overlay),'rename_main':False},
                {'id':'entry','role':'application','language':'c','source':str(main),'directory':str(other),
                 'flags':['-std=c17','-O0','-D','OFFSET=5'],'overlay':None,'rename_main':True},
                {'id':'observer','role':'driver','language':language,'source':str(driver),'directory':str(private),
                 'flags':['-std=c++17' if language=='cpp' else '-std=c11','-O2'],'overlay':None,'rename_main':False}],
            'link':{'language':language,'directory':str(project),'flags':['-pthread']}}
        groups = []
        for unit in recipe['units']:
            depfile = base / ('discovery-' + unit['id'] + '.d')
            compiler = tools.directory / ('clang' if unit['language']=='c' else 'clang++')
            argv = [compiler,*unit['flags'],'-g','-MD','-MF',depfile,'-MT','otelc-inputs','-fsyntax-only',unit['source']]
            if unit['overlay'] is not None: argv += ['-ivfsoverlay',unit['overlay']]
            result = execute(argv, Path(unit['directory']))
            assert result.returncode == 0, result.stderr
            (base / ('discovery-' + unit['id'] + '.stderr')).write_bytes(result.stderr)
            write(base / ('discovery-' + unit['id'] + '.command.json'), list(map(str,argv)))
            target, _, words = depfile.read_text().replace('\\\n','').partition(':')
            assert target == 'otelc-inputs'
            groups.append(tuple((Path(unit['directory']) / name.replace('$$','$')).resolve(strict=True)
                                for name in shlex.split(words)))
        assert header in groups[0]
        policy = Policy.parse({'schema_version':3,'languages':[language],
            'resource':{'service_name':'oteleq-native-unit-probe'},'sources':{'include':['**']},
            'functions':{'include':['work(int)' if language=='cpp' else 'work']},
            'metrics':{'collection':True,'emission':True},'traces':{'enabled':True,'sample_ratio':1.0},
            'export':{'endpoint':'http://127.0.0.1:1','interval_ms':60000,'timeout_ms':1000,'shutdown_timeout_ms':5000}}).data
        app_before = {str(path):facts(path) for path in project.rglob('*') if path.is_file()}
        intent = native_unit_build.freeze(sdk,project,base/'compiled',language,recipe,tuple(groups),policy)
        config_file=base/'policy.toml';config(config_file,policy)
        recipe_file=base/'recipe.json';write(recipe_file,recipe)
        argv=[sys.executable,'-I','-S','-B',SDK/'otelc/cli_bootstrap.py','--config',config_file,'native-build',
              '--language',language,'--root',project,'--recipe',recipe_file,'--output',intent.output,'--sdk-build',sdk.directory]
        write(base/'build.command.json',list(map(str,argv)))
        result=subprocess.run(list(map(str,argv)),cwd=base,env=environment,capture_output=True,timeout=90)
        (base/'build.stdout').write_bytes(result.stdout);(base/'build.stderr').write_bytes(result.stderr)
        assert result.returncode==0,result.stderr.decode(errors='replace')
        built=native_unit_build.read(intent)
        assert json.loads(result.stdout)==built.manifest()
        for plain in (True,False):
            label='plain' if plain else 'woven'
            with capture.receiver() as (endpoint,bodies,errors):
                current=copy.deepcopy(policy);current['export']['endpoint']=endpoint
                policy_file=base/(label+'.toml');config(policy_file,current)
                expected=native_prepared.freeze(built,base/('runtime-'+label),Path(sys.executable).absolute(),policy_file,current,plain=plain)
                argv=[sys.executable,'-I','-S','-B',SDK/'otelc/cli_bootstrap.py','--config',policy_file,'native-run',
                      '--build',intent.output,'--runtime',expected.runtime,'--prepare-only']
                if plain:argv.append('--plain')
                result=execute(argv,base)
                (base/(label+'.prepare.stdout')).write_bytes(result.stdout);(base/(label+'.prepare.stderr')).write_bytes(result.stderr)
                assert result.returncode==0,result.stderr.decode(errors='replace')
                launch=native_prepared.read(expected);session=native_session.Session(launch)
                folder=base/('execution-'+label)
                with native_session.retained(session):
                    result=generation.execute(native_prepared.command(expected),base,env=environment,folder=folder,
                        timeout=30,record_process=True,interaction=session)
                assert result.returncode==0 and result.stderr==b'',(result.returncode,result.stderr)
                assert result.stdout==(b'5|18|7|17\n' if language=='cpp' else b'5|18|7\n'),result.stdout
                assert errors==[]
                capture.retain_http(folder,bodies,errors)
                names=(work.name+'::'+('work(int)' if language=='cpp' else 'work'),)*(2 if language=='cpp' else 1)
                witness=native_telemetry.witness(session.execution,bodies,current['resource']['service_name'],names,folder=folder)
                state['applications'].append({'language':language,'plain':plain,'pid':session.child,
                    'supervisor_pid':session.started.owner.pid,'witness':witness,'build3_files':len(built.files)})
        assert app_before=={str(path):facts(Path(path)) for path in app_before}
        header.write_text('#define BASE 99\n')
        try: built.verify()
        except ValueError: state[language+'_changed_system_header']='refused'
        else: raise AssertionError('changed isystem header accepted')
    state['status']='passed'
except Exception as error:
    traceback.print_exc()
    state.update(status='failed',error=repr(error))
finally:
    after={str(path):facts(path) for path in held_paths};write(ROOT/'inputs-after.json',after)
    state['held_source_and_sdk_facts']=before==after
    if before!=after:state['status']='failed'
    state.update(seconds=round(time.monotonic()-started,3),finished=datetime.now(timezone.utc).isoformat())
    write(ROOT/'status.json',state);print(json.dumps(state,indent=2),flush=True)
    raise SystemExit(0 if state['status']=='passed' else 1)
