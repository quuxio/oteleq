import ctypes,os,sys
from pathlib import Path
library=ctypes.CDLL(os.environ['AUDIT_READER'])
library.inspect_file.argtypes=[ctypes.c_char_p]
library.inspect_file.restype=ctypes.c_int
target=os.environ['AUDIT_ENTRY']
armed=True
def audit(event,args):
    global armed
    if event=='open' and args[0]==target and armed:
        armed=False
        assert library.inspect_file(os.fsencode(target))==112
        Path(target).write_bytes(b"print('after audit')\n")
sys.addaudithook(audit)
