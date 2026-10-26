"""Hash retained build products without modifying them."""
from pathlib import Path
import collections,hashlib,json,datetime
ROOT=Path('/Users/sclarke/github/oteleq-qualification/2026-10-23')
original=json.loads((ROOT/'cpp-large-products-inventory.json').read_text())
rows=[];groups=collections.defaultdict(list)
for item in original['large_files']:
    path=Path(item['path'])
    if path.name not in ('application','application.otelc.json') or path.parent.name!='scratch':continue
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    row={**item,'sha256':digest};rows.append(row);groups[(path.name,digest)].append(row)
record={'finished_at':datetime.datetime.now(datetime.UTC).isoformat(),'products':rows,'unique_identities':len(groups),'hash_identical_extra_copies':sum(len(group)-1 for group in groups.values()),'hash_identical_redundant_bytes':sum(sum(item['bytes'] for item in group[1:]) for group in groups.values()),'logical_bytes':sum(row['bytes'] for row in rows),'distinct_size_groups':len({(Path(row['path']).name,row['bytes']) for row in rows})}
(ROOT/'cpp-retained-product-duplicates.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({k:v for k,v in record.items() if k!='products'},indent=2))
