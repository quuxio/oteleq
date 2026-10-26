import _otelc_inputs as native
import sitecustomize as state
def workload(): return 701
try:
    encoded=native.encode(workload.__code__)
except RuntimeError:
    print('refused',state.calls,state.patched)
else:
    print('encoded',state.calls,state.patched,len(encoded))
