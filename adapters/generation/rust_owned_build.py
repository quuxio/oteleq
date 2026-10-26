"""Bind a rebuilt Rust application to an independently reconstructed fixed exec gate."""

from dataclasses import dataclass, replace
from pathlib import Path

import native_build
import native_inputs as inputs
from native_protocol import require, same
from otelc_capture import path_within, strict_json
import rust_source_build as source_build
from rust_tools import canonical_directory

MANIFEST = 'rust-owned-build.json'
PROFILE = 'rust1981-owned-standalone-v1'
NAMES = (MANIFEST, 'gate/compile.stderr', 'gate/compile.stdout', 'gate/compile_commands.json',
         'gate/gate.json', 'gate/otelc-exec-gate')


@dataclass(frozen=True)
class Intent:
    """The source build and fixed gate source/compiler precede owned output creation."""

    source: source_build.Build
    output: Path
    gate_source: inputs.File
    gate_compiler: inputs.File

    def command(self) -> list[str]:
        """Reconstruct the non-coverage C11 gate recipe without SDK renderers."""
        return [str(self.gate_compiler.path), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                str(self.gate_source.path), '-o', str(self.output / 'gate/otelc-exec-gate')]

    def verify(self) -> None:
        """Recheck original application/tool facts and all physical output boundaries."""
        require(type(self.source) is source_build.Build, 'Rust owned intent needs the original source build')
        self.source.verify()
        original = self.source.intent
        require(type(self.gate_source) is inputs.File and type(self.gate_compiler) is inputs.File
                and self.gate_source.path == original.sdk.root / 'adapters/native/gate/ExecGate.c'
                and self.gate_compiler.path == original.sdk.toolchain.clang.resolved,
                'Rust owned gate source/compiler differs from caller selection')
        self.gate_source.verify()
        self.gate_compiler.verify()
        source_build.outside(replace(original, output=self.output))
        require(not path_within(self.output, original.output), 'Rust owned output overlaps the source build')


def freeze(source: source_build.Build, output: Path) -> Intent:
    """Hold the fixed gate inputs before the SDK compiles the ownership helper."""
    require(type(source) is source_build.Build, 'Rust owned build needs caller-held application inputs')
    source.verify()
    result = Intent(source, output, inputs.capture(source.intent.sdk.root / 'adapters/native/gate/ExecGate.c'),
                    inputs.capture(source.intent.sdk.toolchain.clang.resolved))
    result.verify()
    require(not output.exists(), 'Rust owned output must be a new external directory')
    return result


def envelope(intent: Intent, held: dict[str, inputs.File]) -> dict:
    """The original external source manifest is referenced, never copied or rewritten."""
    return {'schema_version': 1, 'kind': 'otelc.rust.owned-build', 'profile': PROFILE,
            'source_profile': intent.source.manifest()['profile'],
            'source_build': dict(intent.source.files)[source_build.recipe.MANIFEST].gate_identity(),
            'gate': held['gate/gate.json'].gate_identity(), 'source_complete': False}


def gate(intent: Intent, held: dict[str, inputs.File]) -> None:
    """Exact primitive types and compiler-database cwd bind all fixed gate inputs."""
    command = intent.command()
    expected = {'schema_version': 1, 'kind': 'otelc.native.exec-gate',
                'source': intent.gate_source.gate_identity(), 'compiler': intent.gate_compiler.gate_identity(),
                'executable': held['gate/otelc-exec-gate'].gate_identity(), 'coverage': False,
                'command': command, 'source_complete': False}
    require(same(strict_json(held['gate/gate.json'].content), expected),
            'Rust owned gate differs from the fixed source/compiler/product recipe')
    require(same(strict_json(held['gate/compile_commands.json'].content),
                 [{'directory': str(intent.source.intent.sdk.root),
                   'file': str(intent.gate_source.path), 'arguments': command}]),
            'Rust owned gate compiler channel differs from the fixed recipe')


@dataclass(frozen=True)
class Build:
    """Original source and fixed owned output remain held through later preparation."""

    intent: Intent
    files: tuple[tuple[str, inputs.File], ...]

    def manifest(self) -> dict:
        """Return a fresh decoded envelope without sharing mutable intent."""
        return strict_json(dict(self.files)[MANIFEST].content)

    def verify(self) -> None:
        """Repaired envelopes and original source rewrites cannot refresh accepted facts."""
        self.intent.verify()
        require(type(self.files) is tuple and tuple(name for name, _ in self.files) == NAMES
                and native_build.file_set(self.intent.output) == set(NAMES),
                'Rust owned output has missing, extra or aliased files')
        held = dict(self.files)
        for name, file in self.files:
            require(file.path == self.intent.output / name, 'Rust owned output path changed')
            file.verify()
        gate(self.intent, held)
        require(same(self.manifest(), envelope(self.intent, held)),
                'Rust owned envelope differs from original source/gate binding')
        self.intent.verify()


def read(intent: Intent) -> Build:
    """Metadata confirms caller-owned paths; it never selects another source manifest."""
    require(type(intent) is Intent, 'Rust owned reader needs pre-build caller intent')
    intent.verify()
    canonical_directory(intent.output)
    require(native_build.file_set(intent.output) == set(NAMES), 'Rust owned output denominator differs')
    files = tuple((name, inputs.capture(intent.output / name, keep=name.endswith('.json'),
                    maximum=65536 if name.endswith('.json') else inputs.MAX_FILE)) for name in NAMES)
    result = Build(intent, files)
    result.verify()
    return result
