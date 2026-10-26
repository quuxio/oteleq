"""Find older inactive hash-bound native outputs, excluding source/provider inputs."""
from pathlib import Path
import datetime,hashlib,json,os,collections
ROOT=Path('/Users/sclarke/github/oteleq-qualification')
DATE=ROOT/'2026-10-23';exclude=DATE/'cpp-call-sequences'
rows=[];groups=collections.defaultdict(list)
for directory,subdirs,names in os.walk(ROOT):
    path=Path(directory)
    if path==exclude or path.name in ('.git','node_modules','.venv','go-cache','go-validation-cache','target','__pycache__') or path.name.startswith(('target-','validation-env','validation-hash-env')):
        subdirs[:]=[];continue
    if path.name!='scratch' or not path.parent.name.startswith(('baseline-','instrumented_on-')):continue
    attempt=path.parent;identity=attempt/'build-identities.json'
    if not (attempt/'command.json').is_file() or not identity.is_file():continue
    bound=json.loads(identity.read_text()).get('application')
    if not isinstance(bound,str) or len(bound)!=64:continue
    for name in ('application','application.otelc.json'):
        product=path/name
        if not product.is_file() or product.is_symlink():continue
        info=product.stat()
        if info.st_size<1048576:continue
        with product.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if name=='application':assert digest==bound,str(product)
        row={'path':str(product),'bytes':info.st_size,'allocated_bytes':info.st_blocks*512,'sha256':digest}
        rows.append(row);groups[(name,digest)].append(row)
record={'finished_at':datetime.datetime.now(datetime.UTC).isoformat(),'products':rows,'unique_identities':len(groups),'hash_identical_extra_copies':sum(len(group)-1 for group in groups.values()),'hash_identical_redundant_bytes':sum(sum(item['bytes'] for item in group[1:]) for group in groups.values()),'logical_bytes':sum(row['bytes'] for row in rows),'scope':'Other dated folders; only attempt scratch outputs with command.json and a matching application SHA256 binding. Provider inputs, source files, dependencies, build caches and current415 source are excluded.'}
(DATE/'older-retained-native-product-duplicates.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({k:v for k,v in record.items() if k!='products'},indent=2))
