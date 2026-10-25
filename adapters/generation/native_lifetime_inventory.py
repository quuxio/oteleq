"""Bind native lifetime inventories to caller-held frontend facts and tool inputs."""

from dataclasses import dataclass
import gzip
import io
import os
from pathlib import Path
import re
import shlex
import struct

import native_inputs as inputs
import native_unit_build as units
from native_protocol import encoded, fields, require, same
from native_sdk import SDK
from otelc_capture import strict_json

MAX_AST = 64 * 1024 * 1024
TOOL_FILES = ('tool.d', 'tool-dependencies.json', 'tool-dependencies.stderr',
              'tool-build.json', 'tool-build.stderr', 'tool-dependencies-after.json',
              'tool-dependencies-after.stderr', 'native-lifetime-tool.json',
              'compile_commands.json', 'lifetimes')
UNIT_FILES = {
    'object': ('0.d', '0-dependencies.json', '0-dependencies.stderr',
               '0-semantics.stderr', '0-dependencies-after.json',
               '0-dependencies-after.stderr', '0-semantics.json.gz',
               'native-lifetimes.json'),
    'resource': ('source.d', 'dependencies.json', 'dependencies.stderr',
                 'semantics.stderr', 'dependencies-after.json',
                 'dependencies-after.stderr', 'semantics.json.gz',
                 'native-resources.json', 'resolution.json'),
}


def paths(kind: str) -> tuple[str, str]:
    """Only separately negotiated fixed helper and unit directories are read."""
    require(type(kind) is str and kind in UNIT_FILES, 'unsupported native lifetime kind')
    return ('lifetime-tool', 'lifetimes') if kind == 'object' else ('resource-tool', 'resources')


def debug_names(platform: str, target: str | None) -> tuple[str, ...]:
    """Darwin's one-step debug build has three additional fixed compiler products."""
    if platform != 'darwin':
        return ()
    require(type(target) is str and re.fullmatch(r'(arm64|aarch64|x86_64)-apple-[A-Za-z0-9_.-]+', target)
            is not None, 'native semantic tool requires its selected host target')
    architecture = 'x86_64' if target.startswith('x86_64-') else 'aarch64'
    return ('lifetimes.dSYM/Contents/Info.plist',
            'lifetimes.dSYM/Contents/Resources/DWARF/lifetimes',
            'lifetimes.dSYM/Contents/Resources/Relocations/' + architecture + '/lifetimes.yml')


def debug_uuid(raw: bytes, target: str) -> bytes:
    """Match a native thin Mach-O tool to its debug binary without executing either."""
    require(len(raw) >= 32, 'native semantic debug image is truncated')
    magic, cpu, _subtype, _kind, count, size, _flags, _reserved = struct.unpack_from('<8I', raw)
    expected_cpu = 0x01000007 if target.startswith('x86_64-') else 0x0100000C
    require(magic == 0xFEEDFACF and cpu == expected_cpu and 0 < count <= 4096
            and 32 + size <= len(raw), 'unsupported native semantic debug image')
    offset, uuids = 32, []
    for _ in range(count):
        require(offset + 8 <= 32 + size, 'truncated native semantic debug command')
        command, length = struct.unpack_from('<2I', raw, offset)
        require(length >= 8 and offset + length <= 32 + size, 'invalid native semantic debug command')
        if command == 0x1B:
            require(length == 24, 'invalid native semantic UUID command')
            uuids.append(raw[offset + 8:offset + 24])
        offset += length
    require(offset == 32 + size and len(uuids) == 1, 'missing or ambiguous native semantic debug UUID')
    return uuids[0]


def selection(patterns: dict, name: str, *, path: bool = False) -> bool:
    """Use slash-aware source globs and literal brackets, with exclusion precedence."""
    def matches(pattern: str) -> bool:
        parts, index = [], 0
        while index < len(pattern):
            tail = pattern[index:]
            if path and tail.startswith('**/'):
                parts.append('(?:.*/)?'); index += 3
            elif path and tail.startswith('**'):
                parts.append('.*'); index += 2
            else:
                char = pattern[index]
                parts.append(({'*': '[^/]*', '?': '[^/]'} if path else
                              {'*': '.*', '?': '.'}).get(char, re.escape(char)))
                index += 1
        return re.fullmatch(''.join(parts), name, re.DOTALL) is not None

    return any(map(matches, patterns['include'])) and not any(map(matches, patterns['exclude']))


def document(value: object, kind: str) -> dict:
    """Freeze complete frontend facts; absence and exact wire types remain visible."""
    paths(kind)
    categories = ('types', 'constructions', 'variables') if kind == 'object' else (
        'types', 'allocations', 'releases', 'unsupported')
    fields(value, {'schema_version', 'kind', *categories}, 'native lifetime semantics')
    expected_kind = 'otelc.clang.lifetime-semantics' if kind == 'object' else 'otelc.clang.c-resource-semantics'
    require(same(value['schema_version'], 1) and value['kind'] == expected_kind
            and all(type(value[key]) is list for key in categories)
            and sum(map(len, (value[key] for key in categories))) <= 1000000
            and len(encoded(value).encode()) <= MAX_AST, 'invalid native lifetime semantics')
    identities = set()
    for category in categories:
        for row in value[category]:
            require(type(row) is dict and type(row.get('location')) is dict,
                    'native lifetime semantic row is incomplete')
            location = fields(row['location'], {'file', 'offset', 'line', 'column',
                              'debug_file', 'debug_line', 'debug_column'}, 'native semantic location')
            require(all(type(location[key]) is int and 0 <= location[key] <= 2**64 - 1
                        for key in ('offset', 'line', 'column', 'debug_line', 'debug_column'))
                    and all(type(location[key]) is str and '\0' not in location[key]
                            for key in ('file', 'debug_file')), 'invalid native semantic location')
            if category == 'types':
                require(type(row.get('usr')) is str and 0 < len(row['usr']) <= 4096
                        and row['usr'] not in identities and type(row.get('name')) is str,
                        'missing or duplicate native lifetime type')
                identities.add(row['usr'])
                flag = 'dependent' if kind == 'object' else 'complete'
                require(type(row.get(flag)) is bool, 'invalid native lifetime type flag')
    for category in ('constructions', 'variables') if kind == 'object' else ('allocations',):
        require(all(type(row.get('type_usr')) is str and row['type_usr'] in identities
                    for row in value[category]), 'native lifetime site lacks its type binding')
    return strict_json(encoded(value))


def catalogue(value: dict, kind: str, policy: dict, project: Path) -> dict:
    """Recompute selected facts without importing a producer reducer."""
    document(value, kind)

    def selected(row: dict) -> bool:
        source = Path(row['location']['file'])
        return source.is_relative_to(project) and selection(
            policy['sources'], source.relative_to(project).as_posix(), path=True)

    all_types = {row['usr']: row for row in value['types']}
    accepted = {name: row for name, row in all_types.items() if selected(row)
                and selection(policy['lifetimes'], row['name'])
                and (kind != 'object' or not row['dependent'])}
    require(len(accepted) <= 4096, 'native lifetime selected type budget exceeded')
    if kind == 'object':
        return {'types': list(accepted.values()), **{key: [
            {**row, 'type': accepted[row['type_usr']]['name']} for row in value[key]
            if row['type_usr'] in accepted and selected(row)]
            for key in ('constructions', 'variables')}, 'unresolved': []}
    for row in value['unsupported']:
        require(type(row.get('observer')) is bool, 'missing resource observer binding')
        require(not (selected(row) and not row['observer'] and
                     ('type_usr' not in row or row['type_usr'] in accepted)),
                'unsupported selected C resource site')
    allocations, releases = [], []
    for category, result in (('allocations', allocations), ('releases', releases)):
        for row in value[category]:
            require(type(row.get('observer')) is bool, 'missing resource observer binding')
            if not selected(row) or row['observer'] or (category == 'allocations' and row['type_usr'] not in accepted):
                continue
            allowed = ('malloc', 'calloc') if category == 'allocations' else ('free',)
            require(row.get('callee') in allowed and row.get('standard') is True
                    and same(row.get('arguments'), 2 if row['callee'] == 'calloc' else 1),
                    'custom or incompatible C allocator/free binding')
            if category == 'allocations':
                record = accepted[row['type_usr']]
                require(record['complete'] and bool(record['name']), 'resource needs a complete named C type')
                row = {**row, 'type': record['name']}
            result.append(row)
    return {'types': list(accepted.values()), 'allocations': allocations, 'releases': releases}


def dependencies(raw: bytes, directory: Path, expected: tuple[inputs.File, ...],
                 aliases: tuple[inputs.File, ...]) -> list[dict]:
    """Compiler text confirms a frozen set; it cannot select new filesystem reads."""
    target, separator, text = raw.decode('utf-8').replace('\\\n', '').partition(':')
    require(target == 'otelc-inputs' and separator == ':', 'invalid semantic dependency target')
    alias_map = {held.path: held.resolved for held in aliases}
    names = [Path(os.path.abspath(directory / name.replace('$$', '$'))) for name in shlex.split(text)]
    # Repeated includes (including distinct frozen logical aliases) are real
    # compiler observations. Keep the raw channel and bind each input once.
    names = list(dict.fromkeys(alias_map.get(name, name) for name in names))
    held = {item.path: item for item in expected}
    require(set(names) == set(held),
            'semantic compiler dependencies differ from caller discovery')
    return [held[name].gate_identity() for name in names]


@dataclass(frozen=True)
class Tool:
    """Caller-selected tool source, complete frontend headers and shared libraries."""

    sdk: SDK
    kind: str
    source: inputs.File
    dependencies: tuple[inputs.File, ...]
    aliases: tuple[inputs.File, ...]
    library_directory: Path
    libraries: tuple[inputs.File, ...]
    library_aliases: tuple[inputs.File, ...]
    host_target: str | None = None

    def verify(self) -> None:
        """Never refresh accepted identities from an SDK response."""
        self.sdk.verify()
        for held in (self.source, *self.dependencies, *self.aliases, *self.libraries, *self.library_aliases):
            held.verify()

    def commands(self, output: Path) -> tuple[list[str], list[str]]:
        """Derive dependency and helper-build argv from the selected LLVM installation."""
        tools = self.sdk.toolchain
        common = [str(tools.directory / 'clang++'), *tools.cxxflags,
                  '-std=c++17', '-fexceptions', '-O1', '-g']
        query = [*common, '-M', '-MT', 'otelc-inputs', '-MF', str(output / 'tool.d'), str(self.source.path)]
        build = [*common, str(self.source.path), '-L' + str(self.library_directory),
                 '-Wl,-rpath,' + str(self.library_directory), '-lclang-cpp', '-lLLVM',
                 '-o', str(output / 'lifetimes')]
        return query, build


def freeze_tool(sdk: SDK, kind: str, dependencies_: tuple[Path, ...], library_directory: Path,
                libraries: tuple[Path, ...], *, aliases: tuple[Path, ...] = (),
                host_target: str | None = None) -> Tool:
    """The caller discovers all helper inputs before the producer creates products."""
    paths(kind)
    debug_names(sdk.platform, host_target)
    source = sdk.root / ('native/clang/Lifetimes.cpp' if kind == 'object' else 'native/clang/Resources.cpp')
    require(type(dependencies_) is tuple and 1 <= len(dependencies_) <= 10000
            and len(set(dependencies_)) == len(dependencies_) and source in dependencies_,
            'incomplete caller semantic-tool dependencies')
    units.canonical(str(library_directory), directory=True)
    require(type(libraries) is tuple and len(libraries) == 2 and libraries[0] != libraries[1],
            'semantic helper needs selected Clang and LLVM libraries')
    suffix = '.dylib' if sdk.platform == 'darwin' else '.so'
    library_aliases = tuple(inputs.capture(library_directory / ('lib' + name + suffix), allow_links=True)
                            for name in ('clang-cpp', 'LLVM'))
    require(tuple(item.resolved for item in library_aliases) == libraries,
            'semantic helper libraries differ from fixed Clang/LLVM bindings')
    held = tuple(inputs.capture(path) for path in dependencies_)
    result = Tool(sdk, kind, inputs.capture(source), held, units.alias_inputs(aliases, held),
                  library_directory, tuple(inputs.capture(path) for path in libraries), library_aliases, host_target)
    result.verify()
    return result


def read_tool(tool: Tool, output: Path, held: dict[str, inputs.File]) -> dict:
    """Reconstruct all helper receipts and actual compiler-query channels."""
    prefix = paths(tool.kind)[0] + '/'
    _query, command = tool.commands(output / prefix)
    rows = dependencies(held[prefix + 'tool.d'].content, tool.sdk.root, tool.dependencies, tool.aliases)
    expected = {'schema_version': 1 if tool.kind == 'object' else 2,
        'kind': 'otelc.native.lifetime-tool', 'toolchain': tool.sdk.toolchain.metadata(),
        'source': tool.source.gate_identity(), 'libraries': [item.gate_identity() for item in tool.libraries],
        'inputs': rows, 'product': held[prefix + 'lifetimes'].gate_identity(),
        'command': command, 'coverage': False}
    if tool.kind == 'resource':
        expected['semantic_profile'] = 'clang22-c-allocation-v1'
    require(same(strict_json(held[prefix + 'native-lifetime-tool.json'].content), expected),
            'semantic tool recipe or input binding changed')
    require(same(strict_json(held[prefix + 'compile_commands.json'].content), [
        {'directory': str(tool.sdk.root), 'file': str(tool.source.path), 'arguments': command}]),
        'semantic tool compiler database changed')
    for label in ('tool-dependencies.json', 'tool-build.json', 'tool-dependencies-after.json'):
        require(not held[prefix + label].content, 'unexpected semantic-tool stdout')
    if debug_names(tool.sdk.platform, tool.host_target):
        require(debug_uuid(held[prefix + 'lifetimes'].content, tool.host_target) == debug_uuid(
            held[prefix + 'lifetimes.dSYM/Contents/Resources/DWARF/lifetimes'].content, tool.host_target),
            'native semantic tool and debug UUID differ')
    return expected


def semantic_bytes(held: inputs.File) -> bytes:
    """Bound decompression before decoding a retained semantic document."""
    with gzip.GzipFile(fileobj=io.BytesIO(held.content)) as stream:
        raw = stream.read(MAX_AST + 1)
    require(0 < len(raw) <= MAX_AST, 'semantic data exceeds its byte budget')
    return raw


def equivalent_facts(left: dict, right: dict) -> bool:
    """AST catalogues are unordered multisets; duplicate rows still count."""
    return set(left) == set(right) and all(
        sorted(map(encoded, left[key])) == sorted(map(encoded, right[key]))
        if type(left[key]) is list and type(right[key]) is list else same(left[key], right[key])
        for key in left)


def resolution(value: object, selected: dict, directory: Path) -> None:
    """Every source allocation/release keeps its own emitted-call denominator."""
    fields(value, {'schema_version', 'kind', 'source', 'sites'}, 'C resource resolution')
    require(same(value['schema_version'], 1) and value['kind'] == 'otelc.native.c-resource-resolution'
            and value['source'] == selected['source'] and type(value['sites']) is list,
            'invalid C resource resolution')
    sites = [*selected['allocations'], *selected['releases']]
    require(len(value['sites']) == len(sites), 'incomplete C resource emitted-site denominator')
    for actual, site in zip(value['sites'], sites):
        location = site['location']; filename = Path(location['debug_file'])
        if not filename.is_absolute():
            filename = directory / filename
        expected = {'caller': site['caller'], 'file': os.path.normpath(filename),
                    'line': location['debug_line'], 'column': location['debug_column'],
                    'callee': site['callee'], 'type_usr': site.get('type_usr', '')}
        fields(actual, {*expected, 'emitted_calls', 'emitted_callees'}, 'C resource emitted site')
        require(all(same(actual[key], item) for key, item in expected.items())
                and type(actual['emitted_calls']) is int and 0 <= actual['emitted_calls'] <= 1048576
                and type(actual['emitted_callees']) is list
                and len(actual['emitted_callees']) == actual['emitted_calls']
                and all(type(name) is str and name in (('free',) if site['callee'] == 'free' else ('malloc', 'calloc'))
                        for name in actual['emitted_callees']), 'C resource emitted compiler site changed')
