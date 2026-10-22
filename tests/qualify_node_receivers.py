"""Actual JavaScript/TypeScript receiver, mutation and reduced replay qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

import node_receiver_oracle
from qualify_generation import command


METHODS=('add','identity','later','silent','static_only','fail')
SOURCE='''export class Counter {
 static total=0;
 static instances=0;
 static shared=[];
 constructor(start){Counter.instances+=1;this.value=start;this.alias=this;this.shared=Counter.shared;}
 change(amount){this.value+=amount;Counter.total+=amount;Counter.shared.push(amount);}
 add(amount){this.change(amount);return this.value;}
 identity(amount){this.change(amount);return this;}
 async later(amount){await Promise.resolve();return this.add(amount);}
 silent(amount){this.value+=amount+Number(process.execArgv.join(' ').includes('/node/register.mjs'));Counter.total+=amount;return 7;}
 static_only(amount){Counter.total+=amount+Number(process.execArgv.join(' ').includes('/node/register.mjs'));return 7;}
 fail(amount){this.change(amount);throw new TypeError('expected');}
}
function make_counter(start){return new Counter(start);}
'''


def fixture_source(language, node_options=None):
    original = SOURCE.replace('/node/register.mjs', '/node-bootstrap.cjs') if node_options else SOURCE
    if language=='javascript':
        return original
    text=original.replace('constructor(start)','constructor(start:number)').replace('function make_counter(start)','function make_counter(start:number)')
    for method in ('change',*METHODS):
        text=text.replace(method+'(amount){',method+'(amount:number){')
    return text


def prepare(cli,provider,folder,language,methods=METHODS,factory_override=None,wrong_class=False,*,node_options=None):
    folder.mkdir()
    source=folder/'application';source.mkdir()
    filename='sample.mjs' if language=='javascript' else 'sample.mts'
    text=fixture_source(language,node_options)
    if wrong_class:
        text=text.replace('return new Counter(start);','return {};')
    (source/filename).write_text(text)
    config=folder/'equivalence.toml'
    text='schema_version=1\nlanguages='+json.dumps([language])+'\n[functions]\ninclude='+json.dumps(['sample.Counter.'+name for name in methods])+'\n'
    if node_options:
        text+='[adapters.node]\n'+''.join(key+'='+json.dumps(value)+'\n' for key,value in node_options.items())
    for name in methods:
        factory=factory_override or ('make_counter' if name=='silent' else 'Counter')
        text+='\n[[fixtures]]\nfunction='+json.dumps('sample.Counter.'+name)+'\ncases=[[7]]\n'
        text+='receiver={factory='+json.dumps(factory)+',arguments=[10]}\n'
        text+='domains=[{kind="integer",minimum=0,maximum=7}]\n'
        if name=='fail':
            text+='expected_baseline={kind="error",category="exception",type="ecmascript.TypeError.prototype:TypeError"}\n'
    config.write_text(text)
    workspace=Path(command([cli,'plan','--source',source,'--otelc-root',provider,'--workspace-parent',folder,'--config',config],folder,'plan'))
    command([cli,'generate','--workspace',workspace],folder,'generate')
    return workspace


def number(value):
    assert value['kind']=='float' and value['type'] in ('javascript.float64','typescript.float64')
    return struct.unpack('>d',bytes.fromhex(value['bits']))[0]


def fields(graph,reference):
    return next(node['fields'] for node in graph['nodes'] if node['id']==reference['node_id'])


def static_value(graph,name):
    descriptor=fields(graph,graph['roots']['static:Counter.'+name])
    assert descriptor['property:present']['value'] is True
    return descriptor['property:value']


def receiver_value(graph):
    receiver=graph['roots']['receiver']
    data=fields(graph,receiver)
    assert data['property:alias']==receiver
    assert data['property:shared']==static_value(graph,'shared')
    return number(data['property:value'])


def check_report(path,count):
    report=json.loads(path.read_text())
    assert report['source_preserved'] and not report['blocked'] and len(report['cases'])==count
    launches=0
    for case in report['cases']:
        method=case['function'].rsplit('.',1)[-1]
        assert case['exit_code']==int(method in ('silent','static_only'))
        assert case['receiver_fixture']['arguments']==[10.0]
        bundle=json.loads((path.parent/case['case']/'typed-bundle.json').read_text())['cases'][0]
        assert 'receiver' in bundle['contract']['required_roots']
        for lane in ('baseline','instrumented_on'):
            assert len(bundle[lane])==2
            for index, attempt in enumerate(bundle[lane]):
                launches+=1
                raw = path.parent / case['case'] / (lane + '-' + str(index)) / 'observation'
                node_receiver_oracle.check(json.loads(raw.read_bytes()), method, case['arguments'][0], lane == 'instrumented_on')
                observed=attempt['observation'];assert not observed['gaps']
                assert receiver_value(observed['before'])==10
                assert number(static_value(observed['before'],'total'))==0
                assert number(static_value(observed['before'],'instances'))==1
                argument=case['arguments'][0];active=int(lane=='instrumented_on')
                expected=10 if method=='static_only' else 10+argument+(active if method=='silent' else 0)
                assert receiver_value(observed['after'])==expected
                assert number(static_value(observed['after'],'total'))==argument+(active if method=='static_only' else 0)
                outcome=observed['outcome']
                if method=='fail':
                    assert outcome['kind']=='error' and outcome['category']=='exception'
                else:
                    assert outcome['kind']=='return'
                    result=outcome['graph']['roots']['result']
                    if method=='identity':
                        assert result==outcome['graph']['roots']['receiver']
                    else:
                        assert number(result)==(expected if method in ('add','later') else 7)
                if lane=='instrumented_on':
                    assert attempt['execution']['witness']['functions']=={case['function']:1}
    return launches


def framework(workspace,folder,name,count):
    text=command([sys.executable,workspace/'tests/test_equivalence.py'],folder,name,expected=1)
    results=[json.loads(line) for line in text.splitlines()]
    assert len(results)==count
    return sum(check_report(Path(result['report']),1) for result in results)


def controls(cli,provider,folder,language,report,*,node_options=None):
    missing=prepare(cli,provider,folder/'missing',language,methods=('silent',),factory_override='missing_factory',node_options=node_options)
    command([cli,'run','--workspace',missing,'--report-dir',folder/'missing/comparison'],folder,'missing',expected=3)
    observed=json.loads((folder/'missing/comparison/report.json').read_text());assert len(observed['blocked'])==1 and not observed['cases']
    wrong=prepare(cli,provider,folder/'wrong',language,methods=('silent',),wrong_class=True,node_options=node_options)
    command([cli,'run','--workspace',wrong,'--report-dir',folder/'wrong/comparison'],folder,'wrong',expected=4)
    observed=json.loads((folder/'wrong/comparison/report.json').read_text());assert observed['source_preserved'] and observed['cases'][0]['exit_code']==4
    assert len(list((folder/'wrong/comparison').rglob('command.json')))==1
    assert not list((folder/'wrong/comparison').rglob('observation'))
    identity=next(case for case in report['cases'] if case['function'].endswith('.identity'))
    bundle=json.loads((folder/'comparison'/identity['case']/'typed-bundle.json').read_text())
    for lane in ('baseline','instrumented_on'):
        for attempt in bundle['cases'][0][lane]:
            roots=attempt['observation']['outcome']['graph']['roots']
            assert roots['result']==roots['receiver'];roots.pop('receiver')
    altered=folder/'missing-receiver.json';altered.write_text(json.dumps(bundle))
    result=json.loads(command([cli,'compare-observations',altered],folder,'missing-receiver',expected=3))
    assert result['verdict']=='inconclusive' and 'requested roots' in json.dumps(result)
    return 1


def qualify(cli,provider,folder,language,*,node_options=None):
    folder.mkdir()
    workspace=prepare(cli,provider,folder/'complete',language,node_options=node_options)
    command([cli,'run','--workspace',workspace,'--report-dir',folder/'comparison'],folder,'comparison',expected=1)
    launches=check_report(folder/'comparison/report.json',6)
    launches+=framework(workspace,folder,'framework',6)
    exported=folder/'exported'
    command([cli,'export-tests','--workspace',workspace,'--destination',exported],folder,'export-dry-run');assert not exported.exists()
    command([cli,'export-tests','--workspace',workspace,'--destination',exported,'--apply'],folder,'export-apply')
    launches+=framework(exported,folder,'exported-framework',6)
    report=json.loads((folder/'comparison/report.json').read_text())
    selected=next(case for case in report['cases'] if case['function'].endswith('.silent'))
    reduced=folder/'shrinking'
    command([cli,'shrink','--workspace',workspace,'--case',selected['case'],'--report-dir',reduced,'--trials','16'],folder,'shrink',expected=1)
    shrink=json.loads((reduced/'shrink.json').read_text());assert shrink['reduced_arguments']==[0.0] and shrink['status']=='candidate_rule_minimal'
    for path in [reduced/'original/report.json',reduced/'confirmation/report.json',*(Path(trial['report']) for trial in shrink['trials'])]:
        launches+=check_report(path,1)
    launches+=framework(Path(shrink['workspace']),folder,'shrunk-framework',1)
    replay=json.loads(command([cli,'replay','--workspace',Path(shrink['workspace']),'--case',selected['case']],folder,'shrunk-replay',expected=1))
    launches+=check_report(Path(replay['report']),1)
    refused=controls(cli,provider,folder,language,report,node_options=node_options)
    command([cli,'render-report',folder/'comparison/report.json','--output-dir',folder/'presentation'],folder,'presentation',expected=1)
    for path in [workspace,exported,Path(shrink['workspace'])]:
        plan=json.loads((path/'plan.json').read_text())
        assert all(hashlib.sha256((Path(plan['source'])/name).read_bytes()).hexdigest()==value for name,value in plan['source_manifest'].items())
    return {'language':language,'cases':6,'matches':4,'difference_controls':2,'qualified_launches':launches,'refused_control_launches':refused,'shrink_trials':len(shrink['trials']),'source_preserved':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--otelc-root',type=Path,required=True);parser.add_argument('--cli',type=Path,required=True);parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--node-backend',choices=('legacy','source-v1'),default='legacy')
    parser.add_argument('--typescript-compiler',choices=('native','api'),default='native')
    args=parser.parse_args();cli=args.cli.resolve(strict=True);provider=args.otelc_root.resolve(strict=True);destination=args.report_dir.resolve()
    if args.node_backend=='legacy' and args.typescript_compiler!='native':
        parser.error('--typescript-compiler requires --node-backend source-v1')
    node_options={'backend':'source-v1','typescript_compiler':args.typescript_compiler} if args.node_backend=='source-v1' else None
    if destination.is_relative_to(provider) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error('report directory must be new and outside both repositories')
    destination.mkdir(mode=0o700,exist_ok=False)
    os.environ['OTELEQ_PYTHON'],os.environ['OTELEQ_CLI']=sys.executable,str(cli)
    results=[qualify(cli,provider,destination/language,language,node_options=node_options) for language in ('javascript','typescript')]
    summary={'claim':'equivalence over these tests and observations','artefact_class':'diagnostic','cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),
             'node_provider':node_options or {'backend':'legacy'},'languages':results,'actual_application_launches':sum(item['qualified_launches']+item['refused_control_launches'] for item in results),
             'scope':'Declared plain source classes, own data/static descriptors and awaited method completion; no private slots, inherited/prototype mutation, arbitrary mutable inputs, scheduler sequences, other-language receivers or shipping qualification.'}
    (destination/'QUALIFICATION.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
