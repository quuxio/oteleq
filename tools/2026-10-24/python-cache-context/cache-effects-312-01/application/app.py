import os
from pathlib import Path
from urllib.request import Request, urlopen
counter=0
def exercise(value:int)->int:
 global counter
 counter+=value
 root=Path(os.environ["APP_DATA_DIR"])
 data=bytes((value,255))
 (root/"out.bin").write_bytes((root/"seed.bin").read_bytes()+data)
 os.chmod(root/"out.bin",0o600)
 request=Request(os.environ["APP_SERVICE_URL"]+"/observe",data=data,headers={"X-Check":"fixture"},method="POST")
 with urlopen(request) as response:
  if response.status!=201 or response.read()!=b"\x00\xff":return -1
 return 7
