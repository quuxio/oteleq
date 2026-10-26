import sys,_otelc_inputs as native
def encode(code,*,marker=None):return native.encode(code)
def observer(code,offset):
    if code.co_name=='chosen':native.observe(code,offset)
assert native.bind(observer,encode) is True
sys.monitoring.use_tool_id(3,'independent-loader-join')
sys.monitoring.register_callback(3,sys.monitoring.events.PY_START,observer)
sys.monitoring.set_events(3,sys.monitoring.events.PY_START)
import _frozen_importlib_external as external
path=__file__.replace('original.py','target.py')
for index in range(3):
    code=external.SourceFileLoader('target',path).get_code('target')
    namespace={}
    exec(code,namespace)
    print(namespace['chosen'](7),namespace['chosen'](8))
