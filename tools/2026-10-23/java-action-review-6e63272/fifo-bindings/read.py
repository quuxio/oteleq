import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from otelc.prepared_java import PreparedApplication
from otelc import witness
application = PreparedApplication.load(Path(sys.argv[2]))
print('prepared-application-loaded', flush=True)
try:
    witness.load_bindings(Path(sys.argv[3]), application)
except (OSError, ValueError) as error:
    print(type(error).__name__, str(error), flush=True)
else:
    raise AssertionError('special file was accepted')
