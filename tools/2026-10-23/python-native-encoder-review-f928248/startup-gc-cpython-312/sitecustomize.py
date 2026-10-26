import gc,types
calls=0
patched=[]
seen=set()
def changed(value):
    global calls
    calls+=1
    return len(value)
def patch_defaults(phase,info):
    if phase != 'stop': return
    objects=gc.get_objects()
    functions=[value for value in objects if type(value) is types.FunctionType and value.__module__=='otelc.native.encoder']
    for value in objects:
        if type(value) is dict and id(value) not in seen and value.get('_code_type') is types.CodeType and '_len' in value:
            seen.add(id(value))
            patched.append(any(function.__kwdefaults__ is None for function in functions))
            value['_len']=changed
gc.callbacks.append(patch_defaults)
gc.set_threshold(1,1,1)
