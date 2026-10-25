"""Discover a caller-owned lifetime tool context before producer compilation."""

from dataclasses import dataclass
import os
from pathlib import Path
import shlex

import native_inputs as inputs
import native_lifetime_build as builds
import native_lifetime_caller as callers
import native_lifetime_inventory as inventory
from native_protocol import encoded, require
import native_unit_caller

MAX_DEPENDENCIES = 10000
MAX_QUERY_BYTES = 8 * 1024 * 1024


def query(evidence: Path, label: str, argv: list, directory: Path, execute) -> bytes:
    """Retain fixed caller-tool commands and their original bounded channels."""
    words = list(map(str, argv))
    result = execute(words, directory)
    require(type(result.stdout) is bytes and type(result.stderr) is bytes
            and len(result.stdout) <= MAX_QUERY_BYTES and len(result.stderr) <= MAX_QUERY_BYTES,
            'native lifetime frontend query exceeded its byte budget')
    (evidence / (label + '.command.json')).write_text(encoded({
        'argv': words, 'directory': str(directory), 'returncode': result.returncode}) + '\n')
    (evidence / (label + '.stdout')).write_bytes(result.stdout)
    (evidence / (label + '.stderr')).write_bytes(result.stderr)
    require(result.returncode == 0, 'native lifetime frontend query failed; original channels retained')
    return result.stdout


def dependencies(raw: bytes, directory: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Only the trusted prebuild compiler query may discover new input paths."""
    target, separator, text = raw.decode('utf-8', errors='strict').replace('\\\n', '').partition(':')
    require(target == 'otelc-inputs' and separator == ':', 'invalid lifetime caller dependency target')
    words = shlex.split(text)
    require(1 <= len(words) <= MAX_DEPENDENCIES and all('\0' not in word for word in words),
            'invalid lifetime caller dependency count or path')
    logical = tuple(Path(os.path.abspath(directory / word.replace('$$', '$'))) for word in words)
    canonical = tuple(dict.fromkeys(path.resolve(strict=True) for path in logical))
    aliases = tuple(dict.fromkeys(path for path in logical if path.resolve(strict=True) != path))
    return canonical, aliases


@dataclass(frozen=True)
class Context:
    """The original tool/query files cannot be replaced after SDK compilation."""

    tool: inventory.Tool
    directory: Path
    files: tuple[inputs.File, ...]

    def verify(self) -> None:
        """Retain the complete private query tree and original tool input identities."""
        self.tool.verify()
        require(type(self.files) is tuple and all(type(row) is inputs.File for row in self.files),
                'native lifetime frontend requires original file records')
        names = {str(row.path.relative_to(self.directory)) for row in self.files}
        require(len(names) == len(self.files)
                and builds.file_set(self.directory, names) == names,
                'native lifetime frontend evidence set changed')
        for row in self.files:
            row.verify()


def prepare(source: native_unit_caller.Source, kind: str, evidence: Path, execute) -> Context:
    """Freeze source, all helper headers, matched libraries and host before SDK builds."""
    source.verify()
    inventory.paths(kind)
    require(source.sdk.source_profile == 'resource-v1', 'public lifetime frontend requires the complete SDK ABI catalogue')
    callers.new_evidence(evidence, source)
    sdk, tools = source.sdk, source.sdk.toolchain
    helper = sdk.root / 'native/clang' / ('Lifetimes.cpp' if kind == 'object' else 'Resources.cpp')
    depfile = evidence / 'tool.d'
    raw = query(evidence, 'inputs', [tools.directory / 'clang++', *tools.cxxflags,
        '-std=c++17', '-fexceptions', '-O1', '-g', '-M', '-MT', 'otelc-inputs', '-MF', depfile, helper], sdk.root, execute)
    require(not raw, 'native lifetime dependency query emitted unexpected stdout')
    held = inputs.capture(depfile, maximum=MAX_QUERY_BYTES, keep=True)
    paths, aliases = dependencies(held.content, sdk.root)
    libdir = query(evidence, 'libdir', [tools.config.path, '--libdir'], sdk.root, execute).decode('utf-8').strip()
    require(bool(libdir) and '\n' not in libdir and '\0' not in libdir and Path(libdir).is_absolute(),
            'native lifetime frontend requires one absolute LLVM library directory')
    directory = Path(libdir).resolve(strict=True)
    suffix = '.dylib' if sdk.platform == 'darwin' else '.so'
    libraries = tuple((directory / ('lib' + name + suffix)).resolve(strict=True) for name in ('clang-cpp', 'LLVM'))
    host = query(evidence, 'host', [tools.directory / 'clang++', '-print-target-triple'], sdk.root, execute).decode('utf-8').strip()
    require(bool(host) and '\n' not in host and '\0' not in host, 'invalid lifetime frontend host target')
    tool = inventory.freeze_tool(sdk, kind, paths, directory, libraries, aliases=aliases, host_target=host)
    held.verify()
    (evidence / 'context.json').write_text(encoded({'schema_version': 1,
        'kind': 'oteleq.native.lifetime-frontend', 'profile': kind,
        'source': tool.source.gate_identity(), 'inputs': [row.gate_identity() for row in tool.dependencies],
        'libraries': [row.gate_identity() for row in tool.libraries], 'host_target': host,
        'scope': 'Caller discovery before SDK application compilation; no runtime admission'}) + '\n')
    names = {'tool.d', 'context.json', *(label + suffix for label in ('inputs', 'libdir', 'host')
                                       for suffix in ('.command.json', '.stdout', '.stderr'))}
    require(builds.file_set(evidence, names) == names, 'native lifetime frontend query outputs differ')
    result = Context(tool, evidence, tuple(inputs.capture(evidence / name) for name in sorted(names)))
    result.verify()
    source.verify()
    return result
