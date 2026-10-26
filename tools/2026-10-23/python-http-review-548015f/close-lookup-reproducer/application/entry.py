import json,threading,urllib.request
from wsgiref.simple_server import make_server,WSGIRequestHandler
class Body:
    lookups=0
    closes=0
    def __iter__(self): return iter([b'ok'])
    def __getattribute__(self,name):
        if name=='close': Body.lookups+=1
        return object.__getattribute__(self,name)
    def close(self): Body.closes+=1
class Quiet(WSGIRequestHandler):
    def log_message(self,*arguments): pass
def app(environ,start_response):
    start_response('200 OK',[('Content-Type','text/plain'),('Content-Length','2')])
    return Body()
server=make_server('127.0.0.1',0,app,handler_class=Quiet)
worker=threading.Thread(target=server.handle_request)
worker.start()
with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/') as response:
    body=response.read()
worker.join(5)
assert not worker.is_alive()
server.server_close()
print(json.dumps({'close_lookups':Body.lookups,'close_calls':Body.closes,'body':body.hex()}))
