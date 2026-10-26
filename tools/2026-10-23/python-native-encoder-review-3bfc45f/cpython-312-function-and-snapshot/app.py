import gc,types
import _otelc_inputs as native
function=next(value for value in gc.get_objects() if type(value) is types.FunctionType and value.__module__ == 'otelc.native.encoder')
original=function.__kwdefaults__['_len']
snapshots=[value for value in gc.get_objects() if type(value) is dict and value.get('_code_type') is types.CodeType and value.get('_len') is original]
calls=0
def changed(value):
    global calls
    calls+=1
    return len(value)
for value in snapshots:
    value['_len']=changed
def workload(): return 701
try:
    encoded=native.encode(workload.__code__)
except RuntimeError:
    print('refused', calls, len(snapshots))
else:
    print('encoded', calls, len(snapshots), len(encoded))
