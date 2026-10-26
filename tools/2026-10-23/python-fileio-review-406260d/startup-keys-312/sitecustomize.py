import _io
file = _io.FileIO('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-fileio-review-406260d/startup-keys-312/data.bin', 'r')
read = file.read
initialiser = file.__init__
read_hash = hash(read)
init_hash = hash(initialiser)
mapping = {read: 'original', initialiser: 'init'}
members = {read, initialiser}
frozen = frozenset(members)
