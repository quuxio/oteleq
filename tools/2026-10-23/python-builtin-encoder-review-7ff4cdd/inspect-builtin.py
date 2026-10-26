"""Retain the actual builtin-container interpreter facts used in review."""

import _imp
import _json
import _struct
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import sysconfig

BASE = Path(__file__).resolve().parent
library = (Path(sysconfig.get_config_var('LIBDIR')) / sysconfig.get_config_var('LDLIBRARY')).resolve(strict=True)
loaded = ctypes.CDLL(str(library))
assert getattr(loaded, 'PyInit__json') is not None
assert getattr(loaded, 'PyInit__struct') is not None
assert _imp.is_builtin('_json') and _imp.is_builtin('_struct')
assert not hasattr(_json, '__file__') and not hasattr(_struct, '__file__')
record = {'python': sys.version, 'executable': sys.executable, 'cache_tag': sys.implementation.cache_tag,
          'library': str(library), 'library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
          'json_builtin': _imp.is_builtin('_json'), 'struct_builtin': _imp.is_builtin('_struct'),
          'json_file': getattr(_json, '__file__', None), 'struct_file': getattr(_struct, '__file__', None),
          'actual_exported_initialisers': ['PyInit__json', 'PyInit__struct']}
(BASE / 'distribution-31210.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
