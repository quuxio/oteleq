import json,os,tempfile
from pathlib import Path
from unittest.mock import patch
from otelc import python_launch_files as files,python_recipe as recipe
results={}
for case in ['pending','pending_rewrite_cleanup','final_rewrite','three_links','zero_links']:
 with tempfile.TemporaryDirectory() as directory:
  path=Path(directory)/'ready.json';stage=Path(directory)/'stage'
  original=recipe.encoded({'value':'original'}).encode();replacement=recipe.encoded({'value':'replaced'}).encode()
  stage.write_bytes(original);stage.chmod(0o600);os.link(stage,path)
  if case in ['final_rewrite','zero_links']:stage.unlink()
  if case=='three_links':os.link(stage,Path(directory)/'extra')
  real_stat,real_open=os.fstat,os.fdopen;count=0
  def metadata(fd):
   global count
   count+=1
   if count==1 and case=='zero_links':path.unlink()
   info=real_stat(fd)
   if count==1 and case in ['pending_rewrite_cleanup','final_rewrite']:
    path.write_bytes(replacement);os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
    if case=='pending_rewrite_cleanup':stage.unlink()
   return info
  value=None;failure=None;pending=False
  with patch.object(files.os,'fstat',side_effect=metadata),patch.object(files.os,'fdopen',wraps=real_open) as reader:
   try:value=files.read(path)[0]
   except Exception as error:failure=type(error).__name__;pending=isinstance(error,FileNotFoundError)
  results[case]={'returned':value,'failure':failure,'pending_subclass':pending,'fdopen_calls':reader.call_count}
  if case=='pending':
   stage.unlink();results[case]['fresh_poll']=files.read(path)[0]
print(json.dumps(results))