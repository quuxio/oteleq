"""Run maintained receiver cases against one exact frozen public CLI build."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

BASE=Path(__file__).resolve().parent
WT=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-source-provider')
PROVIDER=Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/provider')
ROOT=BASE/sys.argv[1];ROOT.mkdir(mode=0o700)
CLI=ROOT/'quux-oteleq';shutil.copyfile('/Users/sclarke/github/oteleq-qualification/work/node-source-target/debug/quux-oteleq',CLI);CLI.chmod(0o700)
files=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=WT).decode().split('\0')[:-1]
assert len(files)==len(set(files));snapshot=ROOT/'source';snapshot.mkdir()
for name in files:
 p=snapshot/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WT/name,p)
(ROOT/'source.json').write_text(json.dumps({'base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=WT,text=True).strip(),'files':{name:hashlib.sha256((snapshot/name).read_bytes()).hexdigest() for name in files},'cli_sha256':hashlib.sha256(CLI.read_bytes()).hexdigest(),'accepted':False},indent=2)+'\n')
sys.path.insert(0,str(snapshot/'tests'))
import qualify_node_receivers as qualifier
os.environ['OTELEQ_CLI']=str(CLI);os.environ['OTELEQ_PYTHON']=str(PROVIDER/'.venv/bin/python');os.environ['OTELC_NODE']='/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node';os.environ['PYTHONDONTWRITEBYTECODE']='1'
rows=[]
for language,compiler in [('javascript','native'),('typescript','native'),('typescript','api')]:
 folder=ROOT/(language+'-'+compiler);folder.mkdir()
 row={'language':language,'compiler':compiler,'accepted':False};rows.append(row)
 (ROOT/'receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
 try:
  workspace=qualifier.prepare(CLI,PROVIDER,folder/'complete',language,node_options={'backend':'source-v1','typescript_compiler':compiler})
  row['workspace']=str(workspace)
  qualifier.command([CLI,'run','--workspace',workspace,'--report-dir',folder/'comparison'],folder,'comparison',expected=1)
  row['literal_checked_launches']=qualifier.check_report(folder/'comparison/report.json',6)
  row['status']='complete'
 except (AssertionError,ValueError,subprocess.SubprocessError) as error:
  row['status']='failed';row['error']=str(error)[-1800:]
 row['actual_applications']=len(list(folder.rglob('node-source-application.json')))
 (ROOT/'receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
