import _io, json, sitecustomize as early
checks = [hash(early.read) == early.read_hash, hash(early.initialiser) == early.init_hash,
          early.mapping[early.read] == 'original', early.mapping[early.initialiser] == 'init',
          early.read in early.members, early.initialiser in early.members,
          early.read in early.frozen, early.initialiser in early.frozen,
          early.read == _io.FileIO.read.__get__(early.file, _io.FileIO), early.read() == b'abc']
assert all(checks), checks
early.file.close()
print(json.dumps(checks))
