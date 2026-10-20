"""Qualify generated Go bundles, exact channels, detached replay and strict controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'examples'))
import otelc_capture as capture
from qualify_generation import command

SOURCE='''package main
import ("fmt";"os";"runtime/debug")
var state int
func init(){fmt.Print("INIT\\xff\\n");fmt.Fprint(os.Stderr,"ERR\\x00\\n")}
func active()bool{info,ok:=debug.ReadBuildInfo();if !ok{return false};for _,dep:=range info.Deps{if dep.Path=="io.quux.otelc/go"{return true}};return false}
func double(value int)int{state=value;return value*2}
func echo_float(value float64)float64{state=1;return value}
func state_difference(value int)int{state=value;if active(){state++};return 7}
func fail(value int)int{state=value;panic("known")}
func main(){fmt.Println(double(24))}
'''
DIRECT='''package main
import ("fmt";"os";"strings";"syscall")
func init(){if path:=os.Getenv("OTELEQ_INIT_MARKER");path!=""{file,err:=os.OpenFile(path,os.O_CREATE|os.O_WRONLY|os.O_APPEND,0600);if err!=nil{panic(err)};file.WriteString("init\\n");file.Close()}}
func selected(value int)int{return value*3}
func main(){fmt.Printf("OUT\\xff\\x00:%d:%s\\n",selected(24),strings.Join(os.Args[1:],","));fmt.Fprint(os.Stderr,"ERR\\x00\\n");if len(os.Args)>1{if os.Args[1]=="exit"{os.Exit(17)};if os.Args[1]=="signal"{syscall.Kill(syscall.Getpid(),syscall.SIGTERM)}}}
'''


def prepare(cli,provider,folder,old_module=False):
    folder.mkdir();source=folder/'application';source.mkdir();(source/'app.go').write_text(SOURCE)
    if old_module:(source/'go.mod').write_text('module fixture\n\ngo 1.20\n')
    config=folder/'equivalence.toml'
    text='schema_version=1\nlanguages=["go"]\n[functions]\ninclude=["app.double","app.echo_float","app.state_difference","app.fail"]\n'
    for name in ('double','echo_float','state_difference','fail'):
        text+='\n[[fixtures]]\nfunction="app.'+name+'"\ncases=[['+('-0.0' if name=='echo_float' else '7')+']]\n'
        if name=='state_difference':text+='domains=[{kind="integer",minimum=0,maximum=7}]\n'
        if name=='fail':text+='expected_baseline={kind="error",category="panic",type="go.string"}\n'
    config.write_text(text)
    workspace=Path(command([cli,'plan','--source',source,'--otelc-root',provider,'--workspace-parent',folder,'--config',config],folder,'plan'))
    command([cli,'generate','--workspace',workspace],folder,'generate');return workspace


def integer(value):
    assert value['kind']=='integer';return int(value['value'])


def check_report(path,provider,count):
    report=json.loads(path.read_text());assert report['source_preserved'] and not report['blocked'] and len(report['cases'])==count
    launches=0
    for case in report['cases']:
        method=case['function'].rsplit('.',1)[-1];assert case['exit_code']==int(method=='state_difference')
        data=json.loads((path.parent/case['case']/'typed-bundle.json').read_text())['cases'][0]
        assert 'global:state' in data['contract']['required_roots']
        for lane in ('baseline','instrumented_on'):
            assert len(data[lane])==2
            for index,attempt in enumerate(data[lane]):
                launches+=1;observed=attempt['observation'];assert not observed['gaps']
                folder=path.parent/case['case']/(lane+'-'+str(index))
                assert (folder/'stdout').read_bytes()==b'INIT\xff\n' and (folder/'stderr').read_bytes()==b'ERR\x00\n'
                assert integer(observed['before']['roots']['global:state'])==0
                expected=1 if method=='echo_float' else int(case['arguments'][0])+int(method=='state_difference' and lane=='instrumented_on')
                assert integer(observed['after']['roots']['global:state'])==expected
                outcome=observed['outcome']
                if method=='fail':assert outcome['kind']=='error' and outcome['category']=='panic'
                else:
                    assert outcome['kind']=='return';result=outcome['graph']['roots']['result']
                    if method=='echo_float':assert result['kind']=='float' and result['bits']==struct.pack('>d',-0.0).hex()
                    else:assert integer(result)==(7 if method=='state_difference' else 2*int(case['arguments'][0]))
                if lane=='instrumented_on':assert attempt['execution']['witness']['functions']=={case['function']:1}
                identities=json.loads((folder/'build-identities.json').read_text());metadata=capture.go_files(provider,folder/'go-bundle')
                assert identities['baseline']==metadata['files']['baseline'] and identities['application']==metadata['files']['application']
                assert identities['loaded_input_count']>100 and identities['compiler']['version'].startswith('go1.')
    return launches


def framework(workspace,folder,name,provider,count):
    text=command([sys.executable,workspace/'tests/test_equivalence.py'],folder,name,expected=1)
    results=[json.loads(line) for line in text.splitlines()];assert len(results)==count
    return sum(check_report(Path(item['report']),provider,1) for item in results)


def execute_record(command_,cwd,env,folder,name,expected):
    result=capture.execute(command_,cwd,env)
    (folder/(name+'.stdout')).write_bytes(result.stdout);(folder/(name+'.stderr')).write_bytes(result.stderr)
    (folder/(name+'.command.json')).write_text(json.dumps([str(item) for item in command_])+'\n')
    assert result.returncode==expected,(name,result.returncode,result.stderr)
    return result


def direct(provider,folder):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    folder.mkdir();project=folder/'source';project.mkdir();source=project/'app.go';source.write_text(DIRECT)
    policy=folder/'policy.toml';policy.write_text('schema_version=2\nlanguages=["go"]\n[sources]\ninclude=["**"]\n[functions]\ninclude=["app.selected"]\n[traces]\nenabled=true\nroot_sample_ratio=1.0\n[adapters.go]\nbackend="compile"\n[export]\ninterval_ms=50\n')
    tools={'go':capture.selected_tools(provider,'go')['go']};service='oteleq-go-bundle-detached'
    env=capture.environment(project,tools,service,provider);marker=folder/'init-marker';env['OTELEQ_INIT_MARKER']=str(marker)
    with capture.receiver() as (endpoint,bodies,errors):
        policy.write_bytes(capture.configure(policy.read_bytes(),endpoint))
        commands=capture.go_commands(provider,project,source,policy,tools,env,folder)
        assert not marker.exists() and not bodies and not errors
        install=folder/'runtime-only'
        for relative in ('target/debug/quux-otelc','adapters/go/build/otelc-go'):
            destination=install/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(provider/relative,destination)
        project.rename(folder/'source-unavailable');cwd=folder/'empty-cwd';cwd.mkdir()
        offline={**env,'OTELC_ADAPTER_ROOT':str(install/'adapters'),'OTELC_GO':'/missing/go','GOROOT':'/missing/goroot','GOPATH':'/missing/gopath','PATH':'/missing/path','OTELC_REPORT_PATH':str(folder/'runtime.json')}
        prefix=[install/'target/debug/quux-otelc','--config',policy,'go']
        for lane,flag in [('baseline','--run-baseline'),('instrumented_on','--run')]:
            result=execute_record(prefix+[flag,folder/'go-bundle','normal','payload'],cwd,offline,folder,lane,0)
            assert result.stdout==b'OUT\xff\x00:72:normal,payload\n' and result.stderr==b'ERR\x00\n'
            if lane=='baseline':assert not bodies
        capture.retain_http(folder,bodies,errors);assert not errors
        witness=capture.witness(bodies,json.loads((folder/'runtime.json').read_text()),{'functions':{'app.selected':1},'trees':1,'errors':0},service,ExportTraceServiceRequest,'go')
        (folder/'witness.json').write_text(json.dumps(witness,indent=2)+'\n')
        for mode,status in [('exit',17),('signal',-signal.SIGTERM)]:
            for lane,flag in [('baseline','--run-baseline'),('instrumented_on','--run')]:
                result=execute_record(prefix+[flag,folder/'go-bundle',mode],cwd,offline,folder,lane+'-'+mode,status)
                assert result.stdout==b'OUT\xff\x00:72:'+mode.encode()+b'\n' and result.stderr==b'ERR\x00\n'
        assert marker.read_text()=='init\n'*6
        refused=0
        for name,replacement in [('selection',('app.selected','app.other')),('traces',('enabled=true','enabled=false'))]:
            changed=folder/(name+'.toml');changed.write_text(policy.read_text().replace(*replacement))
            result=execute_record([install/'target/debug/quux-otelc','--config',changed,'go','--run',folder/'go-bundle'],cwd,offline,folder,name,1)
            assert result.stdout==b'';refused+=1
        for name,change in [('binary',lambda bundle:(bundle/'application').write_bytes(b'changed')),
                            ('empty-modules',lambda bundle:empty_graphs(bundle)),
                            ('missing-recipe',lambda bundle:(bundle/'recipe.json').unlink())]:
            bundle=folder/name;shutil.copytree(folder/'go-bundle',bundle);change(bundle)
            result=execute_record(prefix+['--run',bundle],cwd,offline,folder,name,1)
            assert result.stdout==b'';refused+=1
        architecture=json.loads((folder/'go-build-identities.json').read_text())['compiler']['environment']['GOARCH']
        changed_env={**offline,'GOARCH':'amd64' if architecture=='arm64' else 'arm64'}
        result=execute_record(prefix+['--run-baseline',folder/'go-bundle'],cwd,changed_env,folder,'target',1)
        assert not result.stdout;refused+=1
        assert marker.read_text()=='init\n'*6
        capture.retain_http(folder,bodies,errors)
    return {'qualified_launches':2,'termination_control_launches':4,'prelaunch_refusals':refused,'build_executed_init_or_main':False,'source_unavailable':True,'runtime_only_install':True}


def empty_graphs(bundle):
    manifest=json.loads((bundle/'build.json').read_text())
    for name in ('modules-original.json','modules-instrumented.json'):
        original=json.loads((bundle/name).read_text())
        (bundle/name).write_text(json.dumps({'Settings':original['Settings'],'Modules':{}}))
        manifest['files'][name]=hashlib.sha256((bundle/name).read_bytes()).hexdigest()
    (bundle/'build.json').write_text(json.dumps(manifest))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--otelc-root',type=Path,required=True);parser.add_argument('--cli',type=Path,required=True);parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();provider=args.otelc_root.resolve(strict=True);cli=args.cli.resolve(strict=True);folder=args.report_dir.resolve()
    if folder.is_relative_to(provider) or folder.is_relative_to(Path(__file__).resolve().parents[1]):parser.error('report directory must be new and outside both repositories')
    folder.mkdir(mode=0o700,exist_ok=False);os.environ['OTELEQ_PYTHON']=sys.executable;os.environ['OTELEQ_CLI']=str(cli)
    workspace=prepare(cli,provider,folder/'complete')
    command([cli,'run','--workspace',workspace,'--report-dir',folder/'comparison'],folder,'comparison',expected=1)
    launches=check_report(folder/'comparison/report.json',provider,4)
    launches+=framework(workspace,folder,'framework',provider,4)
    exported=folder/'exported';command([cli,'export-tests','--workspace',workspace,'--destination',exported],folder,'export-dry-run');assert not exported.exists()
    command([cli,'export-tests','--workspace',workspace,'--destination',exported,'--apply'],folder,'export-apply');launches+=framework(exported,folder,'exported-framework',provider,4)
    report=json.loads((folder/'comparison/report.json').read_text());target=next(case for case in report['cases'] if case['function']=='app.state_difference')
    original=next(case for case in report['cases'] if case['function']=='app.double')
    altered=json.loads((folder/'comparison'/original['case']/'typed-bundle.json').read_text())
    for lane in ('baseline','instrumented_on'):
        for attempt in altered['cases'][0][lane]:attempt['observation']['after']['roots'].pop('global:state')
    missing=folder/'missing-state.json';missing.write_text(json.dumps(altered))
    verdict=json.loads(command([cli,'compare-observations',missing],folder,'missing-state',expected=3))
    assert verdict['verdict']=='inconclusive' and 'requested roots' in json.dumps(verdict)
    reduced=folder/'shrinking';command([cli,'shrink','--workspace',workspace,'--case',target['case'],'--report-dir',reduced,'--trials','16'],folder,'shrink',expected=1)
    shrink=json.loads((reduced/'shrink.json').read_text());assert shrink['reduced_arguments']==[0] and shrink['status']=='candidate_rule_minimal'
    for path in [reduced/'original/report.json',reduced/'confirmation/report.json',*(Path(item['report']) for item in shrink['trials'])]:launches+=check_report(path,provider,1)
    launches+=framework(Path(shrink['workspace']),folder,'shrunk-framework',provider,1)
    replay=json.loads(command([cli,'replay','--workspace',Path(shrink['workspace']),'--case',target['case']],folder,'shrunk-replay',expected=1));launches+=check_report(Path(replay['report']),provider,1)
    old=prepare(cli,provider,folder/'old-module',old_module=True)
    command([cli,'run','--workspace',old,'--report-dir',folder/'old-module/comparison'],folder,'old-module',expected=4)
    assert not list((folder/'old-module/comparison').rglob('command.json'))
    assert any(b'instrumentation would change Go language version' in path.read_bytes() for path in (folder/'old-module/comparison').rglob('go-build.log'))
    control=direct(provider,folder/'direct')
    for path in [workspace,exported,Path(shrink['workspace'])]:
        plan=json.loads((path/'plan.json').read_text());assert all(hashlib.sha256((Path(plan['source'])/name).read_bytes()).hexdigest()==value for name,value in plan['source_manifest'].items())
    result={'claim':'equivalence over these tests and observations','artefact_class':'diagnostic','cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),
            'cases':4,'matching_cases':3,'difference_controls':1,'generated_qualified_launches':launches,'direct_controls':control,
            'actual_application_launches':launches+control['qualified_launches']+control['termination_control_launches'],'source_preserved':True,
            'scope':'Standalone generated scalar callers and fixed detached replay; no general Go package/build integration, cgo/workspaces, SDK dependency isolation, recording-off/fault lane or shipping qualification.'}
    (folder/'QUALIFICATION.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)


if __name__=='__main__':main()
