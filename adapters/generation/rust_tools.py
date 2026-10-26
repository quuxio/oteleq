"""Independently bind the rebuilt SDK's retained Rust compiler and bridge tools."""

from dataclasses import dataclass
from pathlib import Path

import native_inputs as inputs
from native_protocol import require, same
import otelc_capture as capture

MANIFEST = 'rust-compiler-tools.json'
PROFILE = 'rust1981-llvm22-sync-v1'
HOSTS = ('aarch64-apple-darwin', 'x86_64-unknown-linux-gnu', 'aarch64-unknown-linux-gnu')
PRODUCTS = ('compiler/debug/otelc-rust-compiler', 'bridge/release/libotelc_rust_bridge.rlib')


def canonical_directory(path: Path) -> None:
    """The caller selects an existing physical root before metadata is read."""
    require(isinstance(path, Path) and path.is_absolute() and path != Path('/')
            and path.resolve(strict=True) == path and path.is_dir() and not path.is_symlink(),
            'Rust tools require a canonical caller-selected directory')


def source_paths(root: Path) -> tuple[Path, ...]:
    """Reconstruct the SDK's ordered Rust source and locked build inputs."""
    canonical_directory(root)
    native = root / 'native/rust'
    canonical_directory(native)
    paths = tuple(capture.tree_paths(native))
    require(not any(path.is_symlink() for path in paths), 'Rust SDK sources contain a linked input')
    required = {native / (role + '/' + name) for role, name in (
        ('compiler', 'Cargo.toml'), ('compiler', 'Cargo.lock'), ('compiler', 'src/main.rs'),
        ('bridge', 'Cargo.toml'), ('bridge', 'Cargo.lock'), ('bridge', 'src/lib.rs'))}
    sources = (*sorted(path for path in paths if path.suffix == '.rs'),
               *sorted(path for path in paths if path.name == 'Cargo.toml'),
               *sorted(path for path in paths if path.name == 'Cargo.lock'), root / 'otelc/rust_compiler.py')
    require(7 <= len(sources) <= 4096 and len(set(sources)) == len(sources)
            and required <= set(sources), 'Rust SDK source/lock denominator is incomplete')
    return sources


@dataclass(frozen=True)
class Compiler:
    """Caller-held native compiler query results and fixed tool identities."""

    sysroot: Path
    host: str
    version: str
    files: tuple[inputs.File, ...]

    def verify(self) -> None:
        """Check the independently selected host/query and original tool facts."""
        canonical_directory(self.sysroot)
        require(type(self.host) is str and self.host in HOSTS and type(self.version) is str
                and len(self.version.encode()) <= 32768 and '\0' not in self.version,
                'invalid caller Rust host/version context')
        require(self.version.startswith('rustc 1.98.1 ') and
                {'release: 1.98.1', 'LLVM version: 22.1.8', 'host: ' + self.host}
                <= set(self.version.splitlines()), 'Rust compiler version differs from the supported profile')
        libraries = sorted((self.sysroot / 'lib').glob('librustc_driver-*'))
        require(len(libraries) == 1, 'Rust compiler requires one original driver library')
        expected = (self.sysroot / 'bin/rustc', self.sysroot / 'bin/cargo', *libraries)
        require(tuple(file.path for file in self.files) == expected, 'Rust selected compiler paths changed')
        for file in self.files:
            file.verify()


def compiler(rustc: Path, sysroot: Path, *, host: str, version: str) -> Compiler:
    """Capture the caller's actual compiler/sysroot query results, without execution."""
    canonical_directory(sysroot)
    require(rustc == sysroot / 'bin/rustc', 'Rust compiler is not the selected sysroot binary')
    libraries = sorted((sysroot / 'lib').glob('librustc_driver-*'))
    require(len(libraries) == 1, 'Rust compiler requires one original driver library')
    value = Compiler(sysroot, host, version, tuple(inputs.capture(path) for path in
        (rustc, sysroot / 'bin/cargo', *libraries)))
    value.verify()
    return value


@dataclass(frozen=True)
class Tools:
    """Consumer-owned source/product expectations; metadata cannot select new paths."""

    root: Path
    directory: Path
    compiler: Compiler
    sources: tuple[inputs.File, ...]
    products: tuple[inputs.File, ...]
    record: inputs.Record

    def expected(self) -> dict:
        """Return fresh metadata from the fixed input and product paths."""
        return {'schema_version': 1, 'kind': 'otelc.rust.compiler-tools', 'profile': PROFILE,
                'sysroot': str(self.compiler.sysroot), 'host': self.compiler.host,
                'version': self.compiler.version,
                'sources': [file.gate_identity() for file in self.sources],
                'tools': [file.gate_identity() for file in self.compiler.files],
                'products': [file.gate_identity() for file in self.products], 'source_complete': False}

    def verify(self) -> None:
        """Recheck complete original facts and the closed record without compiling."""
        canonical_directory(self.root)
        canonical_directory(self.directory)
        self.compiler.verify()
        require(tuple(file.path for file in self.sources) == source_paths(self.root),
                'Rust SDK source denominator changed')
        require(tuple(file.path for file in self.products) == tuple(self.directory / name for name in PRODUCTS),
                'Rust compiler product paths changed')
        require(self.record.file.path == self.directory / MANIFEST, 'Rust tool record path changed')
        for file in (*self.sources, *self.products):
            file.verify()
        self.record.verify()
        require(same(self.record.value(), self.expected()), 'Rust tool record differs from caller-owned inputs')


def read(root: Path, directory: Path, selected: Compiler) -> Tools:
    """Read current tools using an independent context and fixed source/product paths."""
    require(type(selected) is Compiler, 'Rust tools need the caller-held compiler context')
    canonical_directory(root)
    canonical_directory(directory)
    selected.verify()
    sources = tuple(inputs.capture(path) for path in source_paths(root))
    products = tuple(inputs.capture(directory / name) for name in PRODUCTS)
    record = inputs.read(directory / MANIFEST, maximum=8 * 1024 * 1024)
    result = Tools(root, directory, selected, sources, products, record)
    result.verify()
    return result
