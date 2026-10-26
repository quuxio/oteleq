"""Literal compiler metadata and ordinary files; no compiler or SDK is executed."""

import copy
import json
from pathlib import Path

import rust_inventory as inventory


class Fixture:
    """Keep source expectations independent of the metadata being tested."""

    def __init__(self, base: Path) -> None:
        self.project = base / 'application'
        self.output = base / 'build'
        self.project.mkdir()
        self.output.mkdir()
        self.main = self.project / 'main.rs'
        self.types = self.project / 'types_\u00b5.rs'
        self.main.write_text('pub fn run(x: i64) -> i64 { x + 1 }\n' + ' ' * 256)
        self.types.write_text('pub struct W\u00eddget(pub i64);\n' + ' ' * 256)
        self.sources = inventory.capture_sources(self.project, (self.types, self.main))
        self.function = self.declaration(self.main, 'otelc_app::run')
        self.type_source = self.declaration(self.types, 'otelc_app::W\u00eddget')
        self.inspect = {'schema_version': 1, 'kind': 'otelc.rust.compiler-inventory',
                        'mode': 'inspect', 'definitions': [copy.deepcopy(self.function)],
                        'sources': self.sources.hashes(), 'source_complete': False}
        local = {'local': 2, 'role': 'local', 'source': self.type_source,
                 'compiler_type': self.type_source['compiler_name'],
                 'rendered_type': self.type_source['compiler_name'], 'kind': 'struct',
                 'needs_drop': True, 'size': 8, 'alignment': 8, 'layout_error': None}
        sites = [{'kind': 'construction', 'block': 0, 'statement': 0, 'local': 2,
                  'other': None, 'projected': False, 'cleanup': False, 'unwind': None},
                 {'kind': 'drop', 'block': 1, 'statement': None, 'local': 2,
                  'other': None, 'projected': False, 'cleanup': False, 'unwind': 'Continue'}]
        self.body = {'function': self.function, 'phase': 'Runtime(PostCleanup)',
                     'local_count': 4, 'block_count': 3, 'argument_count': 1,
                     'locals': [local], 'unavailable_locals': [], 'sites': sites}
        self.target = 'aarch64-apple-darwin'
        self.lifetime = {'schema_version': 2, 'kind': 'otelc.rust.lifetime-inventory',
                         'sources': self.sources.hashes(), 'target': self.target,
                         'pointer_width': 64, 'bodies': [self.body], 'skipped': [],
                         'source_complete': False, 'instrumentation_complete': False}
        self.policy = {'sources': {'include': ['**/*.rs'], 'exclude': []},
                       'functions': {'include': ['otelc_app::*'], 'exclude': []},
                       'lifetimes': {'enabled': True, 'include': ['otelc_app::*'], 'exclude': []}}

    def declaration(self, path: Path, name: str) -> dict:
        return {'identity': path.relative_to(self.project).as_posix() + '::' + name,
                'file': str(path), 'compiler_name': name, 'start': 0, 'end': 24,
                'asynchronous': False, 'expanded': False}

    def write(self, name: str, value: dict) -> Path:
        path = self.output / name
        path.write_text(json.dumps(value, ensure_ascii=False))
        return path

    def unavailable(self, *, local: int = 3) -> dict:
        return {'local': local, 'role': 'local', 'compiler_type': 'foreign::Value',
                'rendered_type': 'foreign::Value<Wrapper>', 'kind': 'foreign_adt', 'needs_drop': True}
