"""Literal rebuilt Rust tool records exercise independent file/metadata binding."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import rust_tools


def fact(path: Path) -> dict:
    """Build a literal SDK-format identity independently of the consumer reader."""
    info = path.stat()
    return {'path': str(path), 'resolved_path': str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': info.st_size,
            'device': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode,
            'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'links': info.st_nlink, 'uid': info.st_uid, 'gid': info.st_gid}


class RustToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.sdk = self.base / 'sdk'
        self.output = self.base / 'tools'
        self.sysroot = self.base / 'sysroot'
        self.host = 'aarch64-apple-darwin'
        self.version = ('rustc 1.98.1 (literal fixture)\nrelease: 1.98.1\n'
                        'LLVM version: 22.1.8\nhost: ' + self.host + '\n')
        source_names = ['native/rust/bridge/src/lib.rs', 'native/rust/compiler/src/main.rs',
                        'native/rust/bridge/Cargo.toml', 'native/rust/compiler/Cargo.toml',
                        'native/rust/bridge/Cargo.lock', 'native/rust/compiler/Cargo.lock',
                        'otelc/rust_compiler.py']
        tool_names = ['bin/rustc', 'bin/cargo', 'lib/librustc_driver-fixture.dylib']
        self.sources = [self.write(self.sdk / name, b'literal source/lock input') for name in source_names]
        self.tools = [self.write(self.sysroot / name, b'literal native tool') for name in tool_names]
        self.products = [self.write(self.output / name, b'literal product, never executed')
                         for name in rust_tools.PRODUCTS]
        self.value = {'schema_version': 1, 'kind': 'otelc.rust.compiler-tools',
                      'profile': 'rust1981-llvm22-sync-v1', 'sysroot': str(self.sysroot),
                      'host': self.host, 'version': self.version,
                      'sources': [fact(path) for path in self.sources],
                      'tools': [fact(path) for path in self.tools],
                      'products': [fact(path) for path in self.products], 'source_complete': False}
        self.write_record()

    def write(self, path: Path, raw: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def write_record(self) -> None:
        (self.output / rust_tools.MANIFEST).write_text(json.dumps(self.value))

    def compiler(self, **changes) -> rust_tools.Compiler:
        context = {'host': self.host, 'version': self.version} | changes
        return rust_tools.compiler(self.tools[0], self.sysroot, **context)

    def read(self) -> rust_tools.Tools:
        return rust_tools.read(self.sdk, self.output, self.compiler())

    def test_literal_tools_reconstruct_exact_records_without_sdk_or_compiler_execution(self) -> None:
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not execute')):
            held = self.read()
            self.assertEqual(held.expected(), self.value)
            held.verify()
        altered = held.expected()
        altered['products'].clear()
        self.assertEqual(len(held.expected()['products']), 2)

    def test_closed_profiles_and_all_identity_denominators_refuse_rehashed_substitution(self) -> None:
        changes = [('schema_version', True), ('kind', 'otelc.native.compiler-tools'),
                   ('profile', 'rust1981-llvm22-sync-v2'), ('host', 'wrong-host'),
                   ('version', self.version + 'substituted'), ('sysroot', '/foreign'),
                   ('sources', []), ('tools', []), ('products', []), ('source_complete', 0),
                   ('extra', False)]
        original = copy.deepcopy(self.value)
        for key, value in changes:
            self.value = original | {key: value}
            self.write_record()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.read()
        self.value = original
        del self.value['kind']
        self.write_record()
        with self.assertRaises(ValueError):
            self.read()

    def test_original_sources_products_tools_and_record_facts_stay_held(self) -> None:
        for kind in ('source', 'tool', 'product', 'record'):
            with self.subTest(kind=kind):
                held = self.read()
                path = {'source': self.sources[0], 'tool': self.tools[0],
                        'product': self.products[0], 'record': self.output / rust_tools.MANIFEST}[kind]
                original = path.read_bytes()
                path.write_bytes(original + b' changed')
                with self.assertRaises(ValueError):
                    held.verify()
                path.write_bytes(original)
                with self.assertRaises(ValueError):
                    held.verify()
                # Each next subcase starts with a new, explicitly recorded fixture.
                self.value['sources'] = [fact(p) for p in self.sources]
                self.value['tools'] = [fact(p) for p in self.tools]
                self.value['products'] = [fact(p) for p in self.products]
                self.write_record()

    def test_added_source_or_missing_lock_cannot_shrink_the_fixed_source_denominator(self) -> None:
        held = self.read()
        extra = self.sdk / 'native/rust/compiler/src/added.rs'
        extra.write_text('literal new module')
        with self.assertRaises(ValueError):
            held.verify()
        extra.unlink()
        lock = self.sdk / 'native/rust/bridge/Cargo.lock'
        lock.unlink()
        with self.assertRaises(ValueError):
            self.read()

    def test_metadata_cannot_redirect_the_reader_to_a_foreign_tool_or_product(self) -> None:
        foreign = self.base / 'never-read'
        self.value['products'][0]['path'] = str(foreign)
        self.write_record()
        with self.assertRaises(ValueError):
            self.read()
        self.assertFalse(foreign.exists())

    def test_linked_sources_products_and_driver_library_are_refused(self) -> None:
        for kind in ('source', 'product', 'library'):
            with self.subTest(kind=kind):
                path = {'source': self.sources[0], 'product': self.products[0], 'library': self.tools[2]}[kind]
                original = path.read_bytes()
                target = self.base / ('linked-' + kind)
                target.write_bytes(original)
                path.unlink()
                path.symlink_to(target)
                with self.assertRaises(ValueError):
                    self.read()
                path.unlink()
                path.write_bytes(original)
                self.value['sources'] = [fact(p) for p in self.sources]
                self.value['products'] = [fact(p) for p in self.products]
                self.value['tools'] = [fact(p) for p in self.tools]
                self.write_record()

    def test_independent_compiler_host_version_sysroot_and_library_are_required(self) -> None:
        for changed in ({'host': True}, {'host': 'unsupported'}, {'version': True},
                        {'version': self.version.replace('1.98.1', '1.98.2')},
                        {'version': self.version.replace('22.1.8', '22.1.9')},
                        {'version': self.version.replace(self.host, 'x86_64-unknown-linux-gnu')},
                        {'version': self.version + '\0'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.compiler(**changed)
        with self.assertRaises(ValueError):
            rust_tools.compiler(self.tools[1], self.sysroot, host=self.host, version=self.version)
        self.write(self.sysroot / 'lib/librustc_driver-extra.dylib', b'extra driver')
        with self.assertRaises(ValueError):
            self.compiler()

    def test_reader_requires_the_explicit_compiler_context_and_canonical_roots(self) -> None:
        with self.assertRaises(ValueError):
            rust_tools.read(self.sdk, self.output, None)
        alias = self.base / 'sdk-alias'
        alias.symlink_to(self.sdk, target_is_directory=True)
        with self.assertRaises(ValueError):
            rust_tools.read(alias, self.output, self.compiler())
        with self.assertRaises(ValueError):
            rust_tools.canonical_directory(Path('relative'))


if __name__ == '__main__':
    unittest.main()
