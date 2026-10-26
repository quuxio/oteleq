"""Re-audit complete literal graphs and real native/SDK evidence with no new apps."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-live-metrics')
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples'), str(SOURCE / 'tests')]
import generation
import python_inputs
import qualify_python_generated_origins as origins
from qualify_python_caches import recompute_case
from python_sequence_fixture import boundaries


def graph(value: int, total: int, argument: int, *, result: bool = False) -> dict:
    """Literal declared source state; node identities preserve the receiver cycle."""
    integer = lambda number: {'type': 'int', 'value': str(number)}
    roots = {'arguments': {'ref': 0}, 'global:created': integer(1), 'global:global_total': integer(total),
             'receiver': {'ref': 1}, 'static:Counter.total': integer(total)}
    if result:
        roots['result'] = integer(value)
    return {'roots': roots, 'nodes': [
        {'type': 'builtins.list', 'items': [integer(argument)]},
        {'type': '_oteleq_target.Counter', 'fields': [['value', integer(value)], ['alias', {'ref': 1}]]}]}


def main() -> None:
    run = ROOT / 'smoke-04'
    before = generation.manifest(run)
    workspace = Path((run / 'plan.stdout').read_text().strip())
    plan = generation.read(workspace / 'plan.json')
    document = generation.read(run / 'comparison/report.json')
    assert len(document['cases']) == 1 and document['cases'][0]['exit_code'] == 0
    case = document['cases'][0]
    assert case['function'] == 'app.Counter.add' and case['arguments'] == [1]
    entry, = (row for row in document['inventory'] if row['otelc_function'] == case['function'])
    folder = run / 'comparison' / case['case']
    steps, total = [], 0
    for index, argument in enumerate([1,2,3,4,5]):
        initial = graph(10 + total, total, argument)
        total += argument
        steps.append({'id':'step-' + str(index), 'action':'call', 'gaps':[], 'before':initial,
                      'outcome':{'kind':'return','value':graph(10 + total,total,argument,result=True)},
                      'after':graph(10 + total,total,argument)})
    expected = {'before': steps[0]['before'], 'outcome':steps[-1]['outcome'],
                'after':steps[-1]['after'],'steps':steps}
    typed = {**boundaries(expected), 'steps':[{'id':step['id'],'action':'call','gaps':[],**boundaries(step)}
                                           for step in steps]}
    catalogue = plan['artefacts']['python']
    provider = ROOT / 'provider-ce4-312'
    assert python_inputs.artefacts(provider, {'python':Path(sys.executable).absolute()}) == catalogue
    interpreter = origins.interpreter_probe()
    identities = []
    for lane in ('baseline','instrumented_on'):
        for repeat in range(2):
            attempt = folder / (lane + '-' + str(repeat))
            assert generation.read(attempt / 'observation') == expected
            observed = generation.read(attempt / 'typed-observation.json')
            assert observed['gaps'] == []
            assert all(observed[key] == value for key,value in typed.items())
            identities.append(origins.recheck_attempt(attempt,entry,provider,catalogue,interpreter))
    recompute_case(ROOT / 'smoke-cli-01/quux-oteleq',folder / 'typed-bundle.json',case['comparison'])
    assert len({row['application_pid'] for row in identities}) == 4
    assert len({row['sdk_pid'] for row in identities if not row['plain']}) == 2
    assert generation.manifest(run) == before
    assert python_inputs.artefacts(provider, {'python':Path(sys.executable).absolute()}) == catalogue
    result={'application_launches':4,'sdk_processes':2,'new_target_launches_during_audit':0,
            'complete_literal_raw_and_typed_observations':4,'recomputed_comparisons':1,
            'original_evidence_files_held':len(before),'source_sdk_and_installed_inputs_held':True,
            'identities':identities,'scope':'Initial origin-v2 Python3.12 synchronous controlled receiver only; not full workflow or project qualification.'}
    (ROOT / 'smoke-04-retained-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
