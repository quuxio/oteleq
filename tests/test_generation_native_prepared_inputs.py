"""Native prepared protocols and original file facts are independently bound."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_inputs as inputs
import native_protocol as protocol


class NativeProtocolTests(unittest.TestCase):
    def test_closed_descriptor_refuses_every_substitution_without_fallback(self):
        expected = {'schema_version': 1, 'kind': 'otelc.native.protocols', 'profile': 'native-owned-v1',
                    'build': 2, 'request': 1, 'plan': 1, 'prepared': 1, 'command': 1,
                    'execution': 1, 'host_release': 1, 'gate': 1, 'embedded_sdk': True, 'source_complete': False}
        self.assertEqual(protocol.verify_protocols(expected), expected)
        for key in expected:
            changed = copy.deepcopy(expected)
            changed[key] = 1 if type(changed[key]) is bool else True if type(changed[key]) is int else 'unsupported'
            with self.subTest(key=key), self.assertRaises(ValueError):
                protocol.verify_protocols(changed)
        for changed in ({}, {**expected, 'extra': False}, None, []):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                protocol.verify_protocols(changed)

    def test_digest_uses_finite_compact_json_and_exact_primitive_types(self):
        value = {'z': 2, 'a': True}
        self.assertEqual(protocol.encoded(value), '{"a":true,"z":2}')
        self.assertEqual(protocol.digest(value), hashlib.sha256(b'{"a":true,"z":2}').hexdigest())
        self.assertFalse(protocol.same(1, True)); self.assertFalse(protocol.same(1, 1.0))
        with self.assertRaises(ValueError): protocol.digest({'bad': float('nan')})
        self.assertEqual(protocol.fields(value, {'a', 'z'}, 'fixture'), value)
        with self.assertRaises(ValueError): protocol.fields(value, {'a'}, 'fixture')


class NativeInputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / 'input'
        self.path.write_bytes(b'original')

    def test_stable_identity_views_are_fresh_and_original_facts_stay_held(self):
        held = inputs.capture(self.path, keep=True)
        self.assertEqual(held.content, b'original')
        self.assertEqual(held.identity(), {'path': str(self.path), 'resolved_path': str(self.path),
            'sha256': hashlib.sha256(b'original').hexdigest(), 'size': 8})
        info = self.path.stat()
        self.assertEqual(held.gate_identity(), {**held.identity(), 'device': info.st_dev, 'inode': info.st_ino,
            'mode': info.st_mode, 'uid': info.st_uid, 'gid': info.st_gid, 'mtime_ns': info.st_mtime_ns,
            'ctime_ns': info.st_ctime_ns, 'links': info.st_nlink})
        self.assertEqual(held.tool_identity(), {key: held.identity()[key] for key in ('path', 'sha256', 'size')})
        altered = held.identity(); altered['sha256'] = '0' * 64
        held.verify()
        self.assertNotEqual(altered, held.identity())

    def test_changed_bytes_and_restored_bytes_with_new_facts_are_refused(self):
        held = inputs.capture(self.path)
        self.path.write_bytes(b'changed')
        with self.assertRaises(ValueError): held.verify()
        self.path.write_bytes(b'original')
        os.utime(self.path, ns=(held.facts[6] + 1, held.facts[6] + 1))
        with self.assertRaises(ValueError): held.verify()

    def test_only_explicit_tools_can_use_symlinks_and_link_changes_refuse(self):
        link = self.root / 'tool'; link.symlink_to('input')
        with self.assertRaises(ValueError): inputs.capture(link)
        held = inputs.capture(link, allow_links=True)
        self.assertEqual(held.identity()['symlink'], 'input')
        held.verify()
        link.unlink(); link.symlink_to(str(self.path))
        with self.assertRaises(ValueError): held.verify()

    def test_private_file_requires_owned_mode0600_and_one_link(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): inputs.capture(self.path, private=True)
        self.path.chmod(0o600)
        inputs.capture(self.path, private=True).verify()
        os.link(self.path, self.root / 'extra')
        with self.assertRaises(ValueError): inputs.capture(self.path, private=True)

    def test_invalid_budgets_relative_names_directories_and_fifos_refuse(self):
        for maximum in (0, True, -1, inputs.MAX_FILE + 1):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                inputs.capture(self.path, maximum=maximum)
        for path in (Path('relative'), self.root, self.root / 'x/../input'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                inputs.capture(path)
        with self.assertRaises(ValueError): inputs.capture(self.path, maximum=1)
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        with self.assertRaises(ValueError): inputs.capture(fifo)

    def test_json_records_are_finite_closed_objects_with_fresh_decoded_values(self):
        for raw in (b'[]', b'{"a":1,"a":2}', b'{"x":NaN}'):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError): inputs.read(self.path)
        self.path.write_text('{"nested":{"value":7}}')
        held = inputs.read(self.path)
        held.value()['nested']['value'] = 8
        self.assertEqual(held.value(), {'nested': {'value': 7}})
        held.verify()
        self.path.write_text('{"nested":{"value":8}}')
        with self.assertRaises(ValueError): held.verify()

    def test_private_directory_identity_allows_children_but_refuses_mode_and_aliases(self):
        self.root.chmod(0o700)
        before = inputs.directory(self.root)
        (self.root / 'another').write_text('new child')
        self.assertEqual(before, inputs.directory(self.root))
        self.root.chmod(0o755)
        with self.assertRaises(ValueError): inputs.directory(self.root)
        self.root.chmod(0o700)
        alias = self.root / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): inputs.directory(alias)


if __name__ == '__main__':
    unittest.main()
