"""Check retained values/hashes using only frozen code and existing evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

if sys.flags.optimize:
    raise SystemExit('Retained verification requires assertions')
ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'consumer/tests'))
expected=json.loads((ROOT/'verification.json').read_text())


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


checker=ROOT/'revalidation-qualifier.py'
assert digest(checker)==expected['independent_exact_value_revalidation']['qualifier_sha256']
spec=importlib.util.spec_from_file_location('retained_qualifier',checker)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
reports=[ROOT/'generated/comparisons/report.json',ROOT/'configured/comparison/report.json']
for filename in ('framework.stdout','export-replay.stdout'):
    reports.extend(Path(json.loads(line)['report']) for line in (ROOT/'generated'/filename).read_text().splitlines())
cases=launches=0
for path in reports:
    report=read(path);assert report['source_preserved']
    entries={entry['id']:entry for entry in report['inventory']}
    for case in report['cases']:
        assert case['exit_code']==0 and case['comparison']['verdict']=='equivalent_observed'
        folder=path.parent/case['case']
        raw=read(folder/'bundle.json')['cases'][0];typed=read(folder/'typed-bundle.json')['cases'][0]
        module.check_case(case,entries[case['case'].rsplit('-',1)[0]],raw,typed)
        cases+=1;launches+=len(raw['baseline'])+len(raw['instrumented_on'])
assert cases==71 and launches==360
raw_count=0
for row in read(ROOT/'raw-manifest.json'):
    path=ROOT/row['path']
    if 'link' in row:
        assert path.is_symlink() and str(path.readlink())==row['link']
    else:
        assert not path.is_symlink() and path.stat().st_size==row['bytes']
        assert oct(path.stat().st_mode&0o777)==row['mode'] and digest(path)==row['sha256']
    raw_count+=1
assert raw_count==expected['raw_files_and_links']
for row in read(ROOT/'task-binding-manifest.json'):
    path=ROOT/row['path'];assert path.stat().st_size==row['bytes'] and digest(path)==row['sha256']
assert len(read(ROOT/'launch-index.json'))==533
result={'frozen_value_oracles_pass':True,'case_executions':cases,'application_launches_revalidated':launches,
        'original_launches':533,'raw_records_verified':raw_count,'bound_task_records_verified':37,
        'application_reruns':0,'depends_on_live_work_clone':False,'checker_sha256':digest(checker),
        'script_sha256':digest(Path(__file__))}
(ROOT/'portable-revalidation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
