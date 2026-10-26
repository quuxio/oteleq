"""Bind genuine SDK builds to independently frozen caller frontend observations."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
OUT = BASE / 'development-02'
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-lifetime-build')
SDK_ROOT = Path('/Users/sclarke/github/otelc-qualification/work/c-resource-quality')
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
sys.path[:0] = [str(REPO / 'adapters/generation'), str(REPO / 'examples')]
import native_lifetime_build as reader
import native_lifetime_inventory as semantic
import native_protocol
import native_sdk
import native_toolchain
from otelc_capture import strict_json

OUT.mkdir(mode=0o700)
ENV = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
ENV.update(PYTHONDONTWRITEBYTECODE='1', OTELC_LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config')
STATE = {'status': 'running', 'started': datetime.now(timezone.utc).isoformat(), 'commands': [],
         'scope': 'Uncommitted consumer development snapshot. Genuine C++object/Cresource SDK builds and independent metadata reads only; zero application launches, no generated/retained/runtime admission.',
         'applications': 0, 'cases': {}}


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def execute(argv, cwd):
    words = list(map(str, argv)); index = len(STATE['commands'])
    row = {'argv': words, 'cwd': str(cwd), 'started': datetime.now(timezone.utc).isoformat()}
    STATE['commands'].append(row); write('result.json', STATE)
    start = time.monotonic()
    stdout, stderr = OUT / f'command-{index}.stdout', OUT / f'command-{index}.stderr'
    with stdout.open('xb') as out, stderr.open('xb') as err:
        child = subprocess.Popen(words, cwd=cwd, env=ENV, stdout=out, stderr=err, start_new_session=True)
        try:
            child.wait(timeout=600)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=10)
    row.update(exit_code=child.returncode, seconds=round(time.monotonic()-start, 3))
    write('result.json', STATE)
    assert child.returncode == 0, f'command {index} failed; preserve original channels'
    assert stdout.stat().st_size <= semantic.MAX_AST and stderr.stat().st_size <= 16 * 1024**2
    return subprocess.CompletedProcess(words, child.returncode, stdout.read_bytes(), stderr.read_bytes())


def deps(path, cwd):
    target, sep, text = path.read_text().replace('\\\n', '').partition(':')
    assert target == 'otelc-inputs' and sep == ':'
    logical = tuple(Path(os.path.abspath(cwd / word.replace('$$', '$'))) for word in shlex.split(text))
    canonical = tuple(dict.fromkeys(p.resolve(strict=True) for p in logical))
    aliases = tuple(dict.fromkeys(p for p in logical if p.resolve(strict=True) != p))
    return canonical, aliases


def facts(path):
    info = path.stat()
    with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def snapshot():
    def names(root):
        return subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().rstrip('\0').split('\0')
    consumer = set(names(REPO)) | {'adapters/generation/native_lifetime_build.py', 'adapters/generation/native_lifetime_inventory.py',
        'tests/native_lifetime_fixture.py', 'tests/test_generation_native_lifetime_build.py'}
    return {'consumer': {n: facts(REPO/n) for n in sorted(consumer)},
        'provider': {n: facts(SDK_ROOT/n) for n in names(SDK_ROOT)},
        'sdk_products': {n: facts(SDK_ROOT/'build/quality-sdk'/n) for n in ('native-sdk-build.json', 'libotelc_native_runtime.dylib')}}


before = snapshot(); write('inputs-before.json', before)
started = time.monotonic()
try:
    tools = native_toolchain.capture(Path('/opt/homebrew/opt/llvm@22/bin/llvm-config'),
        Path('/opt/homebrew/opt/llvm@22/bin/clang++'), 'cpp', OUT, execute)
    sdk = native_sdk.capture(SDK_ROOT, SDK_ROOT/'build/quality-sdk', tools,
        cmake=Path('/opt/homebrew/bin/cmake'), ninja=Path('/opt/homebrew/bin/ninja'), source_profile='resource-v1')
    cli = [PYTHON, '-I', '-S', '-B', SDK_ROOT/'otelc/cli_bootstrap.py']
    for kind in ('object', 'resource'):
        case = OUT/kind; case.mkdir(mode=0o700)
        project = case/'application'; project.mkdir(mode=0o700)
        language = 'cpp' if kind == 'object' else 'c'
        source = project/('main.cpp' if kind == 'object' else 'main.c')
        source.write_text('''struct Item { int value; explicit Item(int n):value(n){} ~Item(){value=0;} };
int workload(int n) { Item item(n); return item.value+2; }
int main() { return workload(3)==5 ? 0 : 1; }
''' if kind == 'object' else '''#include <stdlib.h>
struct Item { int value; };
int workload(int n) { struct Item *item=malloc(sizeof *item); if(!item)return -1; item->value=n; int value=item->value; free(item); return value+2; }
int main() { return workload(3)==5 ? 0 : 1; }
''')
        version = 4 if kind == 'object' else 5
        native_protocol.verify_protocols(strict_json(execute([*cli, 'native-protocols', '--build-version', str(version)], SDK_ROOT).stdout), build_version=version)
        tool_source = SDK_ROOT/'native/clang'/('Lifetimes.cpp' if kind == 'object' else 'Resources.cpp')
        common = [tools.directory/'clang++', *tools.cxxflags, '-std=c++17', '-fexceptions', '-O1', '-g']
        helper_dep = case/'caller-tool.d'
        execute([*common, '-M', '-MT', 'otelc-inputs', '-MF', helper_dep, tool_source], SDK_ROOT)
        tool_dependencies, tool_aliases = deps(helper_dep, SDK_ROOT)
        libdir = tools.directory.parent/'lib'
        libraries = tuple((libdir/('lib'+name+'.dylib')).resolve(strict=True) for name in ('clang-cpp', 'LLVM'))
        host_target = execute([tools.directory/'clang++', '-print-target-triple'], OUT).stdout.decode().strip()
        tool = semantic.freeze_tool(sdk, kind, tool_dependencies, libdir, libraries, aliases=tool_aliases, host_target=host_target)
        helper = case/'caller-tool'; helper.mkdir(mode=0o700)
        _query, build = tool.commands(helper); execute(build, SDK_ROOT); tool.verify()
        flags = ['-std=c++17' if kind == 'object' else '-std=c11', '-O0', '-fexceptions', '-pthread', '-I', str(project)]
        compiler = tools.directory/('clang++' if kind == 'object' else 'clang')
        target = execute([compiler, '-print-target-triple'], project).stdout.decode().strip() if kind == 'object' else None
        arguments = [compiler, *(['--target='+target] if target else []), *flags, '-g']
        dep = case/'caller-application.d'
        execute([*arguments, '-M', '-MT', 'otelc-inputs', '-MF', dep, source], project)
        application_dependencies, application_aliases = deps(dep, project)
        observations = strict_json(execute([helper/'lifetimes', project, source, '--compile-directory', project, *arguments], project).stdout)
        write(kind+'-caller-semantics.json', observations)
        policy = {'schema_version':3,'languages':[language],'resource':{'service_name':'native-lifetime-reader-development'},
            'sources':{'include':['**'],'exclude':[]},'functions':{'include':['workload*'],'exclude':[]},
            'lifetimes':{'enabled':True,'include':['Item'],'exclude':[],'max_live':4096,'release_methods':['close']},
            'metrics':{'collection':True,'emission':True,'histogram_boundaries_seconds':[1e-6,1e-5,1e-4,.001,.01,.1,1.]},
            'traces':{'enabled':True,'sample_ratio':1.0},'context':{'tasks':False,'http':False},
            'export':{'endpoint':'http://127.0.0.1:1','interval_ms':1000,'timeout_ms':1000,'shutdown_timeout_ms':10000},
            'benchmark':{'iterations':10000,'samples':15,'warmup':5}}
        lines=['schema_version = 3','languages = '+json.dumps([language])]
        for name, values in policy.items():
            if isinstance(values,dict):
                lines.append('['+name+']'); lines.extend(key+' = '+json.dumps(value) for key,value in values.items())
        config=case/'policy.toml'; config.write_text('\n'.join(lines)+'\n')
        recipe={'schema_version':1,'kind':'otelc.native.unit-recipe','assets':[],
            'units':[{'id':'work','role':'application','source':str(source),'language':language,'directory':str(project),
                'flags':flags,'overlay':None,'rename_main':False}],
            'link':{'language':language,'directory':str(project),'flags':['-pthread']}}
        recipe_path=case/'recipe.json';recipe_path.write_text(json.dumps(recipe,indent=2)+'\n')
        intent=reader.freeze(sdk,project,case/'sdk-build',kind,recipe,(application_dependencies,),policy,
            (('work',observations),),tool,target=target,aliases=application_aliases)
        execute([*cli,'--config',config,'native-build','--language',language,'--root',project,
            '--recipe',recipe_path,'--output',intent.base.output,'--sdk-build',sdk.directory],SDK_ROOT)
        accepted=reader.read(intent); accepted.verify()
        STATE['cases'][kind]={'status':'passed','products':len(accepted.files),'tool_dependencies':len(tool_dependencies),
            'application_dependencies':len(application_dependencies),'caller_semantic_types':len(observations['types']),
            'source_build_version':accepted.manifest()['schema_version'],'application_source_unchanged':True}
        write('result.json',STATE)
    STATE['status']='passed'
except Exception as error:
    STATE.update(status='failed',error=repr(error))
finally:
    after=snapshot();write('inputs-after.json',after);STATE['preservation']={key:before[key]==after[key] for key in before}
    if not all(STATE['preservation'].values()): STATE['status']='failed'
    STATE.update(seconds=round(time.monotonic()-started,3),finished=datetime.now(timezone.utc).isoformat())
    write('result.json',STATE);print(json.dumps({k:v for k,v in STATE.items() if k!='commands'},indent=2),flush=True)
    raise SystemExit(0 if STATE['status']=='passed' else 1)
