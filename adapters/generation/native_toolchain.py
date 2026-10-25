"""Derive the native SDK's LLVM recipe from fixed caller-selected tool queries."""

from dataclasses import dataclass
from pathlib import Path
import re
import shlex

import native_inputs as inputs
from native_protocol import require


@dataclass(frozen=True)
class Query:
    """Retain one fixed native tool query and its literal output."""
    command: tuple[str, ...]
    stdout: str


@dataclass(frozen=True)
class Toolchain:
    """Immutable observed tools, flags and original native query channels."""

    version: str
    directory: Path
    config: inputs.File
    clang: inputs.File
    cxx: inputs.File
    selected_compiler: inputs.File
    cxxflags: tuple[str, ...]
    ldflags: tuple[str, ...]
    queries: tuple[Query, ...]

    def verify(self) -> None:
        """Do not re-run tools or replace the caller's originally accepted identities."""
        for held in (self.config, self.clang, self.cxx, self.selected_compiler):
            held.verify()

    def metadata(self) -> dict:
        """The expected SDK metadata is reconstructed without SDK renderers."""
        return {'version': self.version, 'directory': str(self.directory),
                'tools': {'llvm_config': self.config.tool_identity(), 'clang': self.clang.tool_identity(),
                          'clang++': self.cxx.tool_identity()},
                'cxxflags': list(self.cxxflags), 'ldflags': list(self.ldflags)}


def capture(config: Path, compiler: Path, language: str, directory: Path, execute) -> Toolchain:
    """Selected LLVM 22 queries may describe flags; metadata cannot select tools."""
    require(language in ('c', 'cpp'), 'native toolchain requires c or cpp')
    config = config.resolve(strict=True)
    selected, configured = inputs.capture(compiler, allow_links=True), inputs.capture(config)
    queries = []

    def query(path: Path, *arguments: str) -> str:
        """Run only a caller-selected tool and retain its bounded output."""
        result = execute([path, *arguments], directory)
        require(result.returncode == 0 and not result.stderr and type(result.stdout) is bytes
                and len(result.stdout) <= 1024 * 1024, 'native LLVM query failed or exceeded its output budget')
        text = result.stdout.decode('utf-8', errors='strict')
        queries.append(Query(tuple(map(str, (path, *arguments))), text))
        return text.strip()

    version = query(config, '--version')
    require(re.fullmatch(r'22\.[0-9]+\.[0-9]+', version) is not None, 'native provider requires stable LLVM 22')
    tools = Path(query(config, '--bindir'))
    require(tools.is_absolute() and tools == tools.resolve(strict=True) == config.parent,
            'LLVM tools must share the caller-selected config directory')
    clang = inputs.capture(tools / 'clang', allow_links=True)
    cxx = inputs.capture(tools / 'clang++', allow_links=True)
    require(selected.resolved == (clang if language == 'c' else cxx).resolved,
            'native provider compiler differs from caller-selected LLVM')
    for tool in (clang, cxx):
        observed = query(tool.path, '--version')
        match = re.search(r'\bclang version ([0-9]+\.[0-9]+\.[0-9]+)', observed)
        require(match is not None and match[1] == version, 'native compiler/config versions differ')
    cxxflags = tuple(shlex.split(query(config, '--cxxflags')))
    ldflags = tuple(shlex.split(query(config, '--ldflags', '--libs', 'core', 'passes', '--system-libs')))
    require(bool(cxxflags) and bool(ldflags), 'LLVM recipe requires its compiler and linker flags')
    result = Toolchain(version, tools, configured, clang, cxx, selected, cxxflags, ldflags, tuple(queries))
    result.verify()
    return result
