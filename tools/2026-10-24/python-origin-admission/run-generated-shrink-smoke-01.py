from pathlib import Path
import json,os,sys
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-origin-admission')
sys.path[:0]=[str(repo/'tests'),str(repo/'adapters/generation'),str(repo/'examples')]
import generation,python_inputs,python_provider
import qualify_python_sequences as fixture
import qualify_python_generated_origins as verifier
from qualify_project_tests import command
p=Path(__file__).parent/'generated-shrink-smoke-01';p.mkdir(mode=0o700)
provider=Path(__file__).parent/'provider-794ccaa-312'
cli=Path(__file__).parent/'generated-development-target/debug/quux-oteleq'
tools={'python':Path(sys.executable).absolute()};before=python_inputs.artefacts(provider,tools)
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(cli),PYTHONDONTWRITEBYTECODE='1')
workspace=fixture.prepare(cli,provider,p/'cases',methods=('transient',),python_profile=python_provider.ORIGIN_PROFILE)
command([cli,'run','--workspace',workspace,'--report-dir',p/'comparison'],p,'run',1)
verifier.check_report(p/'comparison/report.json',1)
case=generation.read(p/'comparison/report.json')['cases'][0]
command([cli,'shrink','--workspace',workspace,'--case',case['case'],'--report-dir',p/'shrink','--trials','1'],p,'shrink',1)
reduced=generation.read(p/'shrink/shrink.json');assert reduced['reduced_arguments']==[0] and reduced['status']=='candidate_rule_minimal'
retained=Path(reduced['workspace']);original=generation.read(workspace/'plan.json');derived=generation.read(retained/'plan.json')
assert derived['python_provider_manifest']==original['python_provider_manifest']
assert generation.manifest(retained/'python-provider')==original['python_provider_manifest']
command([sys.executable,retained/'tests/test_equivalence.py'],p,'reduced-framework',1)
replay=json.loads(command([cli,'replay','--workspace',retained,'--case',case['case']],p,'reduced-replay',1))
verifier.check_report(Path(replay['report']),1)
assert python_inputs.artefacts(provider,tools)==before
result={'state':'passed','reduced_arguments':reduced['reduced_arguments'],'probe_seal_preserved':True,'retained_framework_and_replay':'expected mutation failure','provider_inputs_preserved':True,'cli_sha256':generation.capture.file_digest(cli)}
generation.write(p/'result.json',result);print(json.dumps(result),flush=True)
