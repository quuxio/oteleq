from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path
import json, os
root=Path(__file__).parent/'presentation-a295-node24'
server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(root)))
record={'pid':os.getpid(),'port':server.server_port,'root':str(root)}
(root/'server.json').write_text(json.dumps(record)+'\n')
print(json.dumps(record),flush=True)
server.serve_forever()
