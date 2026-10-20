"""Qualify declared Python receivers, static roots, mutation controls and replay."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command


ACTIVE = '"quux.otelc" in tuple(sys.monitoring.get_tool(index) for index in range(6))'
SOURCE = '''import sys
class Counter:
 total=0
 instances=0
 shared=[]
 def __init__(self,start:int):
  Counter.instances+=1
  self.value=start
  self.alias=self
  self.shared=Counter.shared
 def _change(self,amount:int):
  self.value+=amount
  Counter.total+=amount
  Counter.shared.append(amount)
 def add(self,amount:int)->int:
  self._change(amount)
  return self.value
 def identity(self,amount:int):
  self._change(amount)
  return self
 def silent(self,amount:int)->int:
  self.value+=amount+int(ACTIVE)
  Counter.total+=amount
  return 7
 def static_only(self,amount:int)->int:
  Counter.total+=amount+int(ACTIVE)
  return 7
 def fail(self,amount:int)->int:
  self._change(amount)
  raise ValueError("expected")
def make_counter(start:int)->Counter:
 return Counter(start)
'''.replace('ACTIVE', ACTIVE)
METHODS = ('add', 'identity', 'silent', 'static_only', 'fail')


def write_policy(path: Path, methods=METHODS, factory_override=None) -> None:
    prefix = 'src.pkg.state.Counter.'
    text = 'schema_version=1\nlanguages=["python"]\n[adapters.python]\nimport_roots=["src"]\n[functions]\ninclude=' + json.dumps([prefix+name for name in methods])+'\n'
    for name in methods:
        factory = factory_override or ('make_counter' if name == 'silent' else 'Counter')
        text += '\n[[fixtures]]\nfunction='+json.dumps(prefix+name)+'\ncases=[[7]]\n'
        text += 'receiver={factory='+json.dumps(factory)+',arguments=[10]}\n'
        text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
        if name == 'fail':
            text += 'expected_baseline={kind="error",category="exception",type="python.builtins.ValueError"}\n'
    path.write_text(text)


def prepare(cli, provider, folder, source_text=SOURCE, methods=METHODS, factory_override=None):
    folder.mkdir()
    source = folder/'application'
    package = source/'src/pkg'
    package.mkdir(parents=True)
    (package/'__init__.py').write_text('')
    (package/'state.py').write_text(source_text)
    policy = folder/'equivalence.toml'
    write_policy(policy, methods, factory_override)
    workspace = Path(command([cli,'plan','--source',source,'--otelc-root',provider,'--workspace-parent',folder,
                              '--config',policy],folder,'plan'))
    command([cli,'generate','--workspace',workspace],folder,'generate')
    return workspace


def receiver_value(graph):
    root = graph['roots']['receiver']
    node = next(item for item in graph['nodes'] if item['id'] == root['node_id'])
    assert node['fields']['property:alias'] == root
    assert node['fields']['property:shared'] == graph['roots']['static:Counter.shared']
    return int(node['fields']['property:value']['value'])


def check_report(path: Path, expected_cases: int) -> int:
    report = json.loads(path.read_text())
    assert report['source_preserved'] and not report['blocked'] and len(report['cases']) == expected_cases
    launches = 0
    for case in report['cases']:
        method = case['function'].rsplit('.',1)[-1]
        different = method in ('silent','static_only')
        assert case['exit_code'] == int(different) and case['receiver_fixture']['arguments'] == [10]
        bundle = json.loads((path.parent/case['case']/'typed-bundle.json').read_text())['cases'][0]
        assert 'receiver' in bundle['contract']['required_roots']
        for lane in ('baseline','instrumented_on'):
            assert len(bundle[lane]) == 2
            for attempt in bundle[lane]:
                launches += 1
                observed = attempt['observation']
                assert not observed['gaps']
                assert receiver_value(observed['before']) == 10
                assert observed['before']['roots']['static:Counter.total']['value'] == '0'
                assert observed['before']['roots']['static:Counter.instances']['value'] == '1'
                argument = case['arguments'][0]
                active = int(lane == 'instrumented_on')
                expected_receiver = 10 if method == 'static_only' else 10+argument+(active if method == 'silent' else 0)
                assert receiver_value(observed['after']) == expected_receiver
                expected_static = argument+(active if method == 'static_only' else 0)
                assert int(observed['after']['roots']['static:Counter.total']['value']) == expected_static
                outcome = observed['outcome']
                if method == 'fail':
                    assert outcome['kind'] == 'error' and outcome['category'] == 'exception'
                else:
                    assert outcome['kind'] == 'return'
                    result = outcome['graph']['roots']['result']
                    if method == 'identity':
                        assert result == outcome['graph']['roots']['receiver']
                    else:
                        assert int(result['value']) == (expected_receiver if method == 'add' else 7)
                if lane == 'instrumented_on':
                    assert attempt['execution']['witness']['functions'] == {case['function']:1}
    return launches


def framework(workspace, folder, name, expected_cases=5, expected_exit=1):
    text = command([sys.executable,workspace/'tests/test_equivalence.py'],folder,name,expected=expected_exit)
    summaries = [json.loads(line) for line in text.splitlines()]
    assert len(summaries) == expected_cases
    return sum(check_report(Path(item['report']),1) for item in summaries)


def refusal_controls(cli, provider, folder):
    missing = prepare(cli,provider,folder/'missing-factory',methods=('silent',),factory_override='missing_factory')
    command([cli,'run','--workspace',missing,'--report-dir',folder/'missing-factory/comparison'],folder,'missing-factory',expected=3)
    report = json.loads((folder/'missing-factory/comparison/report.json').read_text())
    assert len(report['blocked']) == 1 and not report['cases'] and report['source_preserved']
    wrong = prepare(cli,provider,folder/'wrong-class',SOURCE.replace('return Counter(start)','return object()'),methods=('silent',))
    command([cli,'run','--workspace',wrong,'--report-dir',folder/'wrong-class/comparison'],folder,'wrong-class',expected=4)
    report = json.loads((folder/'wrong-class/comparison/report.json').read_text())
    assert report['source_preserved'] and len(report['cases']) == 1 and report['cases'][0]['exit_code'] == 4
    assert len(list((folder/'wrong-class/comparison').rglob('command.json'))) == 1
    assert not list((folder/'wrong-class/comparison').rglob('observation'))
    return 1


def required_receiver_control(cli, destination, report):
    """Keep nodes reachable through a returned alias, isolating the missing root."""
    identity=next(case for case in report['cases'] if case['function'].endswith('.identity'))
    bundle=json.loads((destination/'comparison'/identity['case']/'typed-bundle.json').read_text())
    for lane in ('baseline','instrumented_on'):
        for attempt in bundle['cases'][0][lane]:
            roots=attempt['observation']['outcome']['graph']['roots']
            assert roots['result']==roots['receiver']
            roots.pop('receiver')
    altered=destination/'altered-required-receiver-root.json'
    altered.write_text(json.dumps(bundle))
    observed=json.loads(command([cli,'compare-observations',altered],destination,'altered-required-receiver-root',expected=3))
    assert observed['verdict']=='inconclusive'
    assert 'requested roots' in json.dumps(observed) and 'receiver' in json.dumps(observed)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--otelc-root',type=Path,required=True)
    parser.add_argument('--cli',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args()
    cli,provider,destination=args.cli.resolve(strict=True),args.otelc_root.resolve(strict=True),args.report_dir.resolve()
    if destination.is_relative_to(provider) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error('report directory must be new and outside both repositories')
    destination.mkdir(mode=0o700,exist_ok=False)
    os.environ['OTELEQ_PYTHON'],os.environ['OTELEQ_CLI']=sys.executable,str(cli)
    workspace=prepare(cli,provider,destination/'complete')
    command([cli,'run','--workspace',workspace,'--report-dir',destination/'comparison'],destination,'comparison',expected=1)
    launches=check_report(destination/'comparison/report.json',5)
    launches+=framework(workspace,destination,'framework')
    exported=destination/'exported'
    command([cli,'export-tests','--workspace',workspace,'--destination',exported],destination,'export-dry-run')
    assert not exported.exists()
    command([cli,'export-tests','--workspace',workspace,'--destination',exported,'--apply'],destination,'export-apply')
    launches+=framework(exported,destination,'exported-framework')
    report=json.loads((destination/'comparison/report.json').read_text())
    target=next(case for case in report['cases'] if case['function'].endswith('.silent'))
    reduced=destination/'shrinking'
    command([cli,'shrink','--workspace',workspace,'--case',target['case'],'--report-dir',reduced,'--trials','16'],destination,'shrink',expected=1)
    shrink=json.loads((reduced/'shrink.json').read_text())
    assert shrink['reduced_arguments']==[0] and shrink['status']=='candidate_rule_minimal'
    for path in [reduced/'original/report.json',reduced/'confirmation/report.json',
                 *(Path(trial['report']) for trial in shrink['trials'])]:
        launches+=check_report(path,1)
    launches+=framework(Path(shrink['workspace']),destination,'shrunk-framework',expected_cases=1)
    replay=json.loads(command([cli,'replay','--workspace',Path(shrink['workspace']),'--case',target['case']],destination,'shrunk-replay',expected=1))
    launches+=check_report(Path(replay['report']),1)
    refused_launches=refusal_controls(cli,provider,destination)
    required_receiver_control(cli,destination,report)
    command([cli,'render-report',destination/'comparison/report.json','--output-dir',destination/'presentation'],destination,'presentation',expected=1)
    for path in [workspace,exported,Path(shrink['workspace'])]:
        plan=json.loads((path/'plan.json').read_text())
        assert all(hashlib.sha256((Path(plan['source'])/name).read_bytes()).hexdigest()==value for name,value in plan['source_manifest'].items())
    summary={'claim':'equivalence over these tests and observations','artefact_class':'diagnostic',
             'cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),'cases':5,'matching_cases':3,'difference_controls':2,
             'qualified_application_launches':launches,'refused_control_application_launches':refused_launches,
             'actual_application_launches':launches+refused_launches,'generated_suite_runs':3,
             'counterexample_reduced_from':7,'counterexample_reduced_to':0,'shrink_trials':len(shrink['trials']),
             'refused_controls':['missing factory','wrong receiver class','edited retained receiver root'],
             'source_preserved':True,'scope':'Explicit plain Python receiver constructors/functions, declared own statics and dictionary graphs; no inherited/native slots, external factories, arbitrary mutable inputs, async sequences, other-language receivers or shipping qualification.'}
    (destination/'QUALIFICATION.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    main()
