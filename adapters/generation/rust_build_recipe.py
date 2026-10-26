"""Reconstruct standalone Rust build commands and compiler dependency channels."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from native_protocol import require

if TYPE_CHECKING:
    from rust_source_build import Intent

PROFILES = ('rust1981-standalone-sync-v1', 'rust1981-standalone-drop-v2')
MANIFEST = 'rust-source-build.json'
CHANNELS = ('command.json', 'stdout', 'stderr', 'result.json')


def modes(lifetime: bool) -> tuple[str, ...]:
    """Lifetime discovery remains a distinct compiler operation."""
    return ('inspect', 'lifetime-inspect', 'lifetime-weave') if lifetime else ('inspect', 'weave')


def selection(policy: dict) -> dict:
    """Only build-time selectors enter the compiled selection identity."""
    value = {key: policy[key] for key in ('sources', 'functions')}
    if policy['lifetimes']['enabled']:
        value['lifetimes'] = {key: policy['lifetimes'][key] for key in ('enabled', 'include', 'exclude')}
    return value


def request(intent: Intent, mode: str) -> dict:
    """Reconstruct a fixed request from the caller's pre-build declarations/MIR."""
    value = {'schema_version': 1, 'mode': mode, 'root': str(intent.project), 'entry': str(intent.entry),
             'sources': intent.sources.hashes(), 'selected': intent.selected() if mode.endswith('weave') else [],
             'output': str(intent.output / (mode + '-inventory.json'))}
    if mode == 'lifetime-weave':
        value.update(intent.bindings())
    return value


def commands(intent: Intent) -> tuple[tuple[str, list[str]], ...]:
    """Use fixed executables, matched flags, original cwd and fixed product paths."""
    output, tools, sdk = intent.output, intent.tools, intent.sdk
    flags = [str(intent.entry), '--crate-name', 'otelc_app', '--edition=2024', '--sysroot',
             str(tools.compiler.sysroot), '-Copt-level=' + str(intent.optimisation), '-g']
    compiler = str(tools.compiler.files[0].path)
    driver = str(tools.products[0].path)
    result = [('discover', [compiler, *flags, '--emit=dep-info=' + str(output / 'original.d')])]
    for mode in modes(intent.lifetime):
        argv = [driver, *flags, '-o', str(output / 'instrumented')]
        if mode.endswith('weave'):
            argv += ['--extern', 'otelc_rust_bridge=' + str(tools.products[1].path),
                     '-L', 'native=' + str(sdk.library.path.parent), '-l', 'dylib=otelc_native_runtime',
                     '-C', 'link-arg=' + str(output / 'bootstrap.o'),
                     '-C', 'link-arg=-Wl,-rpath,' + str(sdk.library.path.parent)]
        result.append((mode, argv))
    result[-1:-1] = [
        ('plain', [compiler, *flags, '-o', str(output / 'plain')]),
        ('bootstrap', [str(sdk.toolchain.directory / 'clang++'), '-std=c++17', '-O2', '-c',
                       str(output / 'bootstrap.cpp'), '-I', str(sdk.root / 'adapters/native/launcher/include'),
                       '-o', str(output / 'bootstrap.o')])]
    return tuple(result)


def names(intent: Intent) -> tuple[str, ...]:
    """Enumerate required channels without accepting manifest-selected file paths."""
    fixed = {MANIFEST, 'original.d', 'plain', 'instrumented', 'bootstrap.cpp', 'bootstrap.o'}
    for mode in modes(intent.lifetime):
        fixed.update((mode + '-request.json', mode + '-inventory.json'))
    fixed.update(label + '.' + suffix for label, _ in commands(intent) for suffix in CHANNELS)
    return tuple(sorted(fixed))


def dependency_paths(raw: bytes, project: Path, expected: tuple[Path, ...]) -> None:
    """Decode rustc dep-info escapes and compare paths before any filesystem read."""
    require(len(raw) <= 4 * 1024 * 1024 and b'\0' not in raw, 'invalid Rust dependency channel')
    text = raw.decode('utf-8')
    require(not any(line.startswith('# env-dep:') for line in text.splitlines()),
            'Rust environment dependencies need an explicit retained context')
    joined = text.replace('\\\n', '')
    first = joined.splitlines()[0] if joined else ''
    _, separator, names_ = first.partition(': ')
    require(bool(separator), 'invalid Rust dep-info target separator')
    values, token, index = [], '', 0
    while index < len(names_):
        char = names_[index]
        if char == '\\':
            index += 1
            require(index < len(names_), 'unfinished Rust dependency escape')
            token += names_[index]
        elif names_[index:index + 2] == '$$':
            token += '$'
            index += 1
        elif char.isspace():
            if token:
                values.append(token)
                token = ''
        else:
            token += char
        index += 1
    if token:
        values.append(token)
    paths = tuple(sorted(set(project / value for value in values)))
    require(1 <= len(values) <= 65536 and paths == expected,
            'Rust compiler dependency denominator differs from caller discovery')
