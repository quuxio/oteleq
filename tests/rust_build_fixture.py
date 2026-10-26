"""Literal rebuilt Rust application records; every compiler/product is inert."""

import copy
import hashlib
import json
from pathlib import Path

import native_inputs
import native_provider_fixture as native
import rust_inventory_fixture
import rust_source_build
import rust_tools
from test_generation_rust_tools import fact


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def digest(value: object, *, ascii: bool = True) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=ascii).encode()).hexdigest()


class Fixture:
    """Build independently expected metadata after freezing pre-build caller facts."""

    def __init__(self, base: Path, *, lifetime: bool = False) -> None:
        self.base, self.lifetime = base, lifetime
        self.sdk = native.sdk(base, source_profile='resource-v1')
        self.original = rust_inventory_fixture.Fixture(base)
        self.project = self.original.project
        self.output = base / 'application-build'
        self.sysroot = base / 'rust-sysroot'
        self.tools_directory = base / 'rust-tools'
        self.host = 'x86_64-unknown-linux-gnu'
        self.version = 'rustc 1.98.1 (literal)\nrelease: 1.98.1\nLLVM version: 22.1.8\nhost: ' + self.host + '\n'
        self.original.lifetime['target'] = self.host
        source_names = ('native/rust/bridge/src/lib.rs', 'native/rust/compiler/src/main.rs',
                        'native/rust/bridge/Cargo.toml', 'native/rust/compiler/Cargo.toml',
                        'native/rust/bridge/Cargo.lock', 'native/rust/compiler/Cargo.lock', 'otelc/rust_compiler.py')
        sources = [self.file(self.sdk.root / name) for name in source_names]
        compiler_files = [self.file(self.sysroot / name) for name in
                          ('bin/rustc', 'bin/cargo', 'lib/librustc_driver-literal.so')]
        self.products = [self.file(self.tools_directory / name) for name in
                         ('compiler/debug/otelc-rust-compiler', 'bridge/release/libotelc_rust_bridge.rlib')]
        write(self.tools_directory / 'rust-compiler-tools.json', {
            'schema_version': 1, 'kind': 'otelc.rust.compiler-tools', 'profile': 'rust1981-llvm22-sync-v1',
            'sysroot': str(self.sysroot), 'host': self.host, 'version': self.version,
            'sources': [fact(path) for path in sources], 'tools': [fact(path) for path in compiler_files],
            'products': [fact(path) for path in self.products], 'source_complete': False})
        compiler = rust_tools.compiler(compiler_files[0], self.sysroot, host=self.host, version=self.version)
        self.tools = rust_tools.read(self.sdk.root, self.tools_directory, compiler)
        self.policy = {'schema_version': 3, 'languages': ['rust'], 'resource': {'service_name': 'rust-unit'},
            'export': {'endpoint': 'http://127.0.0.1:4318', 'interval_ms': 1000, 'timeout_ms': 1000,
                       'shutdown_timeout_ms': 10000},
            'sources': {'include': ['**/*.rs'], 'exclude': []},
            'functions': {'include': ['otelc_app::*'], 'exclude': []},
            'metrics': {'collection': True, 'emission': True, 'histogram_boundaries_seconds': [0.001, 1.0]},
            'traces': {'enabled': True, 'sample_ratio': 1.0},
            'lifetimes': {'enabled': lifetime, 'include': ['otelc_app::*'], 'exclude': [],
                          'max_live': 4096, 'release_methods': ['close']},
            'context': {'tasks': False, 'http': False},
            'benchmark': {'iterations': 10000, 'samples': 15, 'warmup': 5}}
        inspected = self.original.write('independent-inspection.json', self.original.inspect)
        self.inspection = native_inputs.read(inspected)
        self.life_inspection = native_inputs.read(self.original.write('independent-MIR.json', self.original.lifetime)) \
            if lifetime else None
        self.dependencies = tuple(file.path for file in self.original.sources.files)
        self.intent = self.freeze()

    def file(self, path: Path, raw: bytes = b'literal inert product') -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def freeze(self, **changes) -> rust_source_build.Intent:
        options = {'lifetime_inspection': self.life_inspection} | changes
        return rust_source_build.freeze(self.tools, self.sdk, self.project, self.original.main,
            self.output, self.dependencies, self.inspection, self.policy, **options)

    def build(self) -> None:
        self.output.mkdir()
        flags = [str(self.original.main), '--crate-name', 'otelc_app', '--edition=2024', '--sysroot',
                 str(self.sysroot), '-Copt-level=2', '-g']
        modes = ('inspect', 'lifetime-inspect', 'lifetime-weave') if self.lifetime else ('inspect', 'weave')
        sources = {str(path): fact(path)['sha256'] for path in self.dependencies}
        selected = [self.original.function['identity']]
        body = self.original.body
        bindings = {'schema_version': 2, 'lifetimes': {self.original.function['identity']: {
            '2': self.original.type_source['compiler_name']}},
            'lifetime_bodies': {self.original.function['identity']: digest(body, ascii=False)}}
        inventories, requests = [], []
        for mode in modes:
            request = {'schema_version': 1, 'mode': mode, 'root': str(self.project),
                'entry': str(self.original.main), 'sources': sources, 'selected': selected if mode.endswith('weave') else [],
                'output': str(self.output / (mode + '-inventory.json'))}
            if mode == 'lifetime-weave': request.update(bindings)
            path = self.output / (mode + '-request.json'); write(path, request); requests.append(fact(path))
            value = copy.deepcopy(self.original.inspect) | {'mode': mode}
            if mode == 'lifetime-inspect': value = self.original.lifetime
            if mode == 'lifetime-weave':
                value.update(bindings, kind='otelc.rust.lifetime-weave', instrumentation_complete=False)
            path = self.output / (mode + '-inventory.json'); write(path, value); inventories.append(fact(path))
        commands = [('discover', [str(self.sysroot / 'bin/rustc'), *flags,
                                  '--emit=dep-info=' + str(self.output / 'original.d')])]
        commands += [(mode, [str(self.products[0]), *flags, '-o', str(self.output / 'instrumented')])
                     for mode in modes]
        commands[-1][1].extend(['--extern', 'otelc_rust_bridge=' + str(self.products[1]),
            '-L', 'native=' + str(self.sdk.directory), '-l', 'dylib=otelc_native_runtime',
            '-C', 'link-arg=' + str(self.output / 'bootstrap.o'),
            '-C', 'link-arg=-Wl,-rpath,' + str(self.sdk.directory)])
        commands[-1:-1] = [
            ('plain', [str(self.sysroot / 'bin/rustc'), *flags, '-o', str(self.output / 'plain')]),
            ('bootstrap', [str(self.sdk.toolchain.directory / 'clang++'), '-std=c++17', '-O2', '-c',
                str(self.output / 'bootstrap.cpp'), '-I', str(self.sdk.root / 'adapters/native/launcher/include'),
                '-o', str(self.output / 'bootstrap.o')])]
        for index, (label, argv) in enumerate(commands):
            write(self.output / (label + '.command.json'), {'arguments': argv, 'cwd': str(self.project)})
            write(self.output / (label + '.result.json'), {'pid': 500 + index, 'exit_code': 0, 'seconds': 0.125})
            for channel in ('stdout', 'stderr'): self.file(self.output / (label + '.' + channel), b'')
        self.file(self.output / 'original.d', ('out: ' + ' '.join(map(str, self.dependencies)) + '\n').encode())
        self.file(self.output / 'bootstrap.cpp', native.BOOTSTRAP.encode())
        self.file(self.output / 'bootstrap.o')
        for lane in ('plain', 'instrumented'): self.file(self.output / lane)
        selection = {key: self.policy[key] for key in ('sources', 'functions')}
        if self.lifetime: selection['lifetimes'] = {key: self.policy['lifetimes'][key]
                                                   for key in ('enabled', 'include', 'exclude')}
        self.value = {'schema_version': 2 if self.lifetime else 1, 'kind': 'otelc.rust.source-build',
            'profile': 'rust1981-standalone-drop-v2' if self.lifetime else 'rust1981-standalone-sync-v1',
            'root': str(self.project), 'entry': str(self.original.main), 'policy': copy.deepcopy(self.policy),
            'policy_sha256': digest(self.policy), 'selection_sha256': digest(selection),
            'tools': fact(self.tools_directory / 'rust-compiler-tools.json'),
            'sdk': fact(self.sdk.directory / 'native-sdk-build.json'),
            'inputs': [fact(path) for path in self.dependencies], 'requests': requests, 'selected': selected,
            'optimisation': 2, 'inventories': inventories,
            'products': [fact(self.output / lane) for lane in ('plain', 'instrumented')], 'source_complete': False}
        self.publish()

    def publish(self) -> None:
        write(self.output / 'rust-source-build.json', self.value)

    def rehash(self, path: Path) -> None:
        for key in ('requests', 'inventories', 'products', 'inputs'):
            for index, row in enumerate(self.value[key]):
                if row['path'] == str(path): self.value[key][index] = fact(path)
        self.publish()
