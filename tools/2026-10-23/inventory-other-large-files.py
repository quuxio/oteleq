"""Classify remaining large qualification files without changing evidence."""
from pathlib import Path
import os,json,collections,datetime
ROOT=Path('/Users/sclarke/github/oteleq-qualification')
rows=[];categories=collections.defaultdict(lambda:{'files':0,'logical_bytes':0})
for directory,subdirs,names in os.walk(ROOT):
    p=Path(directory)
    if p.name=='.git':subdirs[:]=[];continue
    for name in names:
        path=p/name
        try:s=path.lstat()
        except FileNotFoundError:continue
        if path.is_symlink() or s.st_size<1048576:continue
        parts=path.relative_to(ROOT).parts
        if p.name=='scratch' and name in ('application','application.otelc.json'):kind='hash-bound native output candidates'
        elif any(part.startswith('target-') or part=='target' for part in parts):kind='compiler products or remaining generic targets'
        elif 'go-cache' in parts or 'go-validation-cache' in parts:kind='Go build or module cache'
        elif 'node_modules' in parts or '.venv' in parts or any(part.startswith('validation-env') for part in parts):kind='installed dependency or validation environment'
        else:kind=name if name.endswith(('.json','.log','.protobuf','.profraw','.profdata')) else path.suffix or name
        categories[kind]['files']+=1;categories[kind]['logical_bytes']+=s.st_size
        rows.append({'path':str(path),'bytes':s.st_size,'allocated_bytes':s.st_blocks*512,'category':kind})
record={'finished_at':datetime.datetime.now(datetime.UTC).isoformat(),'files_over_1mib':len(rows),'categories':dict(sorted(categories.items(),key=lambda row:row[1]['logical_bytes'],reverse=True)),'files':rows}
(ROOT/'2026-10-23/qualification-large-file-footprint.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({k:v for k,v in record.items() if k!='files'},indent=2))
