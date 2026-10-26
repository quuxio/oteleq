"""Retain exact final source and its data-only identities."""
import hashlib,json,subprocess,tarfile
from pathlib import Path
base=Path(__file__).parent
checkout=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-qualification-retention-fixes')
head='367b599e7fe55a01364810f194b3e54e3c29ab8d'
archive=base/'source-367b599.tar';source=base/'source-367b599'
subprocess.run(['git','archive','--format=tar','-o',str(archive),head],cwd=checkout,check=True)
source.mkdir()
with tarfile.open(archive) as contents: contents.extractall(source,filter='data')
files={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
(base/'source-367b599.json').write_text(json.dumps({'head':head,'parent':'676564618d49bafaf4b7e16990f0da795f1017b2','archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':files},indent=2)+'\n')
print(json.dumps({'head':head,'files':len(files)}))
