"""Independently bind an operator-selected native SDK product and its fixed recipe."""

from dataclasses import dataclass
from pathlib import Path
import sys

import native_inputs as inputs
import otelc_capture as wire
from native_protocol import require, same
from native_toolchain import Toolchain

MANIFEST = 'native-sdk-build.json'
SOURCE_ABIS = {
    'function-v2': ('function_abi.h',),
    'object-v1': ('function_abi.h', 'object_abi.h'),
    'resource-v1': ('function_abi.h', 'object_abi.h', 'resource_abi.h'),
}


def source_paths(root: Path, *, source_profile: str = 'function-v2') -> tuple[Path, ...]:
    """Reconstruct the whole recorded source denominator before reading its record."""
    require(type(source_profile) is str and source_profile in SOURCE_ABIS,
            'unsupported native SDK source profile')
    native = root / 'adapters/native'
    require(native.is_dir() and not native.is_symlink(), 'native SDK source directory is missing or aliased')
    discovered = tuple(wire.tree_paths(native))
    require(not any(path.is_symlink() for path in discovered), 'native SDK source tree contains an aliased input')
    paths = (native / 'CMakeLists.txt', native / 'launcher/CMakeLists.txt',
             *sorted(path for path in discovered if path.suffix == '.cpp'),
             *sorted(path for path in discovered if path.suffix == '.h'),
             *(root / 'native/llvm' / name for name in SOURCE_ABIS[source_profile]))
    require(5 <= len(paths) <= 4096 and len(set(paths)) == len(paths), 'invalid native SDK source denominator')
    return paths


@dataclass(frozen=True)
class SDK:
    """Caller-owned fixed names, tool queries, original facts and selected product."""

    root: Path
    directory: Path
    toolchain: Toolchain
    cmake: inputs.File
    ninja: inputs.File
    sources: tuple[inputs.File, ...]
    library: inputs.File
    record: inputs.Record
    platform: str
    coverage: bool
    homebrew_prefix: bool
    source_profile: str = 'function-v2'

    def expected(self) -> dict:
        """Reconstruct the fixed library recipe from caller-selected inputs."""
        compiler = self.toolchain.directory
        configure = [str(self.cmake.path), '-S', str(self.root / 'adapters/native/launcher'),
            '-B', str(self.directory), '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=RelWithDebInfo',
            '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DCMAKE_C_COMPILER=' + str(compiler / 'clang'),
            '-DCMAKE_CXX_COMPILER=' + str(compiler / 'clang++'),
            '-DOTELC_LAUNCH_COVERAGE=' + ('ON' if self.coverage else 'OFF')]
        if self.homebrew_prefix:
            configure += ['-DCMAKE_PREFIX_PATH=/opt/homebrew/opt/protobuf', '-DCURL_ROOT=/opt/homebrew/opt/curl']
        build = [str(self.cmake.path), '--build', str(self.directory), '--target', 'otelc_native_runtime', '-j', '4']
        return {'schema_version': 1, 'kind': 'otelc.native-sdk-build',
                'sources': [source.identity() for source in self.sources], 'toolchain': self.toolchain.metadata(),
                'build_tools': [tool.identity() for tool in (self.cmake, self.ninja)],
                'commands': [configure, build], 'library': self.library.identity(),
                'coverage': self.coverage, 'source_complete': False}

    def verify(self) -> None:
        """No manifest-selected path, repaired metadata or changed source can replace intent."""
        require(tuple(source.path for source in self.sources)
                == source_paths(self.root, source_profile=self.source_profile), 'native SDK source set changed')
        self.toolchain.verify()
        for held in (self.cmake, self.ninja, self.library, *self.sources):
            held.verify()
        self.record.verify()
        require(same(self.record.value(), self.expected()), 'native SDK record differs from its caller-held recipe')


def capture(root: Path, directory: Path, toolchain: Toolchain, *, cmake: Path, ninja: Path,
            coverage: bool = False, platform: str = sys.platform,
            source_profile: str = 'function-v2') -> SDK:
    """The operator selects source/build/tools; the SDK record only confirms them."""
    require(type(coverage) is bool and platform in ('darwin', 'linux'), 'unsupported native SDK platform or coverage option')
    require(root.is_absolute() and root == root.resolve(strict=True) and root.is_dir() and root != Path('/'),
            'native SDK root must be a canonical source directory')
    require(directory.is_absolute() and directory == directory.resolve(strict=True) and directory.is_dir(),
            'native SDK build must be a canonical existing directory')
    toolchain.verify()
    sources = tuple(inputs.capture(path) for path in source_paths(root, source_profile=source_profile))
    selected_tools = (inputs.capture(cmake, allow_links=True), inputs.capture(ninja, allow_links=True))
    library_name = 'libotelc_native_runtime.' + ('dylib' if platform == 'darwin' else 'so')
    library = inputs.capture(directory / library_name)
    record = inputs.read(directory / MANIFEST)
    result = SDK(root, directory, toolchain, *selected_tools, sources, library, record, platform, coverage,
                 platform == 'darwin' and Path('/opt/homebrew/opt/protobuf').is_dir(), source_profile)
    result.verify()
    return result
