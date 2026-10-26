"""COW-share exact duplicate inactive retained outputs, preserving paths and bytes."""
from pathlib import Path
import ctypes,datetime,hashlib,json,os,stat,subprocess

ROOT=Path('/Users/sclarke/github/oteleq-qualification/2026-10-23')
CORPUS=ROOT/'cpp-call-sequences'
lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
lib.clonefile.argtypes=(ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int)
lib.clonefile.restype=ctypes.c_int
lib.listxattr.argtypes=(ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int)
lib.listxattr.restype=ctypes.c_ssize_t
lib.getxattr.argtypes=(ctypes.c_char_p,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int)
lib.getxattr.restype=ctypes.c_ssize_t


def xattrs(path):
    name=os.fsencode(path)
    size=lib.listxattr(name,None,0,0)
    if size<0:raise OSError(ctypes.get_errno(),'listxattr failed',str(path))
    buffer=ctypes.create_string_buffer(size)
    if lib.listxattr(name,buffer,size,0)!=size:raise OSError('xattr names changed')
    result=[]
    for key in buffer.raw.split(b'\0'):
        if not key:continue
        length=lib.getxattr(name,key,None,0,0,0)
        if length<0:raise OSError(ctypes.get_errno(),'getxattr failed',str(path))
        value=ctypes.create_string_buffer(length)
        if lib.getxattr(name,key,value,length,0,0)!=length:raise OSError('xattr value changed')
        result.append((key,value.raw))
    return tuple(sorted(result))


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def metadata(path):
    s=path.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_flags==0
    return {'device':s.st_dev,'inode':s.st_ino,'mode':stat.S_IMODE(s.st_mode),
            'uid':s.st_uid,'gid':s.st_gid,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,
            'atime_ns':s.st_atime_ns,'links':s.st_nlink,'flags':s.st_flags}


def preserved(before,after):
    return all(before[key]==after[key] for key in ('device','mode','uid','gid','bytes','mtime_ns','links','flags'))


def available():
    value=os.statvfs(CORPUS);return value.f_bavail*value.f_frsize


def verify_published():
    checked=0
    for folder in ('qualification-50f01a7','compatibility-70cbdbc'):
        manifest=CORPUS/(folder+'-raw-manifest.json')
        expected=json.loads(manifest.read_text())
        for name,wanted in expected.items():
            path=CORPUS/folder/name
            assert path.is_file() and not path.is_symlink() and digest(path)==wanted,str(path)
            checked+=1
    return checked


def main():
    result=subprocess.run(['lsof','-nP','-Fpn'],capture_output=True,text=True,check=True)
    opened={line[1:] for line in result.stdout.splitlines() if line.startswith('n')}
    rows=json.loads((ROOT/'cpp-retained-product-duplicates.json').read_text())['products']
    targets={row['path'] for row in rows}
    assert not targets.intersection(opened),'retained products are open'
    receipt=ROOT/'cpp-retained-cow-compaction.json'
    assert not receipt.exists()
    record={'started_at':datetime.datetime.now(datetime.UTC).isoformat(),
            'method':'native APFS clonefile of exact SHA256 matches; distinct inodes and nlink1; no writable hardlinks',
            'scope':'Inactive hash-bound scratch/application and scratch/application.otelc.json outputs only. No source, providers, inputs or runtime/tool roles.',
            'metadata_scope':'Original content, paths, size, mode, uid/gid, flags, xattrs and nanosecond mtime retained. Inode/ctime/birthtime are not part of these retained-output contracts and change on atomic replacement.',
            'available_bytes_before':available(),'published_raw_records_verified_before':verify_published(),'clones':[]}
    receipt.write_text(json.dumps(record,indent=2)+'\n')
    canonical={}
    for row in rows:
        path=Path(row['path'])
        assert path.is_relative_to(CORPUS) and path.parent.name=='scratch' and path.name in ('application','application.otelc.json')
        before=metadata(path);attrs=xattrs(path)
        assert digest(path)==row['sha256'],str(path)
        if path.name=='application':
            identity=json.loads((path.parent.parent/'build-identities.json').read_text())
            assert identity['application']==row['sha256']
        key=(path.name,row['sha256'],before['mode'],before['uid'],before['gid'],attrs)
        if key not in canonical:
            canonical[key]=path;continue
        original=canonical[key]
        temporary=path.with_name('.'+path.name+'.cow-'+str(os.getpid()))
        assert not temporary.exists()
        try:
            if lib.clonefile(os.fsencode(original),os.fsencode(temporary),1)!=0:
                raise OSError(ctypes.get_errno(),'clonefile failed',str(path))
            os.utime(temporary,ns=(before['atime_ns'],before['mtime_ns']))
            after=metadata(temporary)
            assert after['inode'] not in (before['inode'],original.stat().st_ino)
            assert preserved(before,after) and xattrs(temporary)==attrs
            assert digest(temporary)==row['sha256']
            # The original target cannot change between its hash and replacement.
            assert metadata(path)==before
            os.replace(temporary,path)
            final=metadata(path)
            assert preserved(before,final) and xattrs(path)==attrs and digest(path)==row['sha256']
            record['clones'].append({'path':str(path),'canonical':str(original),'sha256':row['sha256'],'bytes':row['bytes'],'original_inode':before['inode'],'clone_inode':final['inode'],'mode':before['mode'],'mtime_ns':before['mtime_ns'],'links':1})
            if len(record['clones'])%25==0:receipt.write_text(json.dumps(record,indent=2)+'\n')
        finally:
            if temporary.exists():temporary.unlink()
    record.update(finished_at=datetime.datetime.now(datetime.UTC).isoformat(),
                  canonical_identities=len(canonical),clone_files=len(record['clones']),
                  exact_duplicate_bytes_shared=sum(row['bytes'] for row in record['clones']),
                  published_raw_records_verified_after=verify_published(),available_bytes_after=available())
    assert record['published_raw_records_verified_before']==record['published_raw_records_verified_after']==10406
    record['available_bytes_delta']=record['available_bytes_after']-record['available_bytes_before']
    record['allocation_note']='Volume delta may include concurrent otelc cleanup; exact_duplicate_bytes_shared is content newly arranged as COW clones, not a claim of exclusive physical-space attribution.'
    receipt.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({key:value for key,value in record.items() if key!='clones'},indent=2))


if __name__=='__main__':main()
