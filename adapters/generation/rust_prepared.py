"""Bind Rust preparation to caller-held policy, original builds and fixed tooling."""

from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
import tomllib

import native_inputs as inputs
from native_protocol import digest, encoded, require, same
from otelc_capture import path_within, strict_json
import rust_build_recipe
import rust_owned_build as owned
import rust_source_build

REQUEST, PLAN, PREPARED = 'rust-request.json', 'rust-plan.json', 'rust-prepared.json'
RECORDS = (REQUEST, PLAN, PREPARED)
REQUIRED = {'__init__.py', '__main__.py', 'cli_bootstrap.py', 'config.py', 'file_inputs.py', 'health.py',
            'llvm_backend.py', 'native_build.py', 'native_gate.py', 'native_launch.py', 'prepared_python.py',
            'prepared_rust.py', 'python_launch_files.py', 'python_sdk_io.py', 'rust_build.py',
            'rust_compiler.py', 'rust_launch.py', 'rust_lifetimes.py', 'rust_owned_build.py', 'rust_supervisor.py'}


def producer_paths(root: Path) -> tuple[Path, ...]:
    """Freeze the installed producer catalogue before SDK preparation creates records."""
    paths = tuple(sorted((root / 'otelc').glob('*.py')))
    require(REQUIRED <= {path.name for path in paths} and len(paths) <= 4096,
            'incomplete Rust preparation producer installation')
    return paths


@dataclass(frozen=True)
class Intent:
    """All caller choices precede preparation; metadata cannot supply new paths/argv."""

    build: owned.Build
    runtime: Path
    python: inputs.File
    interpreter: inputs.File
    producer: tuple[inputs.File, ...]
    policy_file: inputs.File
    policy_json: str
    plain: bool
    arguments: tuple[str, ...]
    wait_ms: int

    def policy(self) -> dict:
        """Return a fresh runtime policy without mutable aliases into accepted intent."""
        return strict_json(self.policy_json)

    def source(self) -> rust_source_build.Build:
        """Keep original application and ownership-gate evidence as separate objects."""
        return self.build.intent.source

    def image(self) -> inputs.File:
        """The caller's lane fixes one original application image."""
        return dict(self.source().files)['plain' if self.plain else 'instrumented']

    def verify(self) -> None:
        """Recheck source/build/tool/policy facts and runtime input boundaries."""
        require(type(self.build) is owned.Build and type(self.plain) is bool
                and type(self.wait_ms) is int and 1 <= self.wait_ms <= 300000,
                'invalid Rust preparation build, lane or host-wait budget')
        self.build.verify()
        require(type(self.arguments) is tuple and len(self.arguments) <= 4096
                and all(type(value) is str and '\0' not in value for value in self.arguments)
                and sum(len(os.fsencode(value)) for value in self.arguments) <= 1024 * 1024,
                'invalid literal Rust application arguments')
        for file in (self.python, self.interpreter, self.policy_file):
            require(type(file) is inputs.File, 'Rust preparation requires caller-held file facts')
            file.verify()
        require(self.python.resolved == self.interpreter.path,
                'Rust preparation interpreter differs from the selected Python spelling')
        require(same(tomllib.loads(self.policy_file.content.decode()), self.policy()),
                'Rust runtime policy bytes differ from frozen caller intent')
        policy = rust_source_build.policy(self.policy())
        initial = self.source().intent.policy()
        require(same(rust_build_recipe.selection(policy), rust_build_recipe.selection(initial))
                and policy['lifetimes']['enabled'] is initial['lifetimes']['enabled'],
                'Rust runtime policy differs from compiled source/function/type selection')
        require(type(self.producer) is tuple and all(type(file) is inputs.File for file in self.producer)
                and tuple(file.path for file in self.producer) == producer_paths(self.source().intent.sdk.root),
                'Rust preparation producer source denominator changed')
        for file in self.producer:
            file.verify()
        outside(self)


def outside(intent: Intent) -> None:
    """Protect original inputs, source/owned builds and the retained policy/interpreter."""
    source = intent.source().intent
    rust_source_build.outside(replace(source, output=intent.runtime))
    require(not any(path_within(intent.runtime, root) for root in (source.output, intent.build.intent.output)),
            'Rust runtime overlaps original application or owned build output')
    require(not any(path_within(intent.runtime, root) for root in
                    (intent.python.path.parent, intent.interpreter.path.parent))
            and not path_within(intent.policy_file.path, intent.runtime)
            and not path_within(intent.interpreter.path, intent.runtime),
            'Rust preparation output contains a caller-held policy or interpreter')


def freeze(build: owned.Build, runtime: Path, python: Path, policy_file: Path, policy: dict, *,
           plain: bool, arguments: tuple[str, ...] = (), wait_ms: int = 30000) -> Intent:
    """Capture operator-selected inputs before the SDK creates a fresh private runtime."""
    require(type(build) is owned.Build, 'Rust preparation requires a caller-held owned build')
    build.verify()
    selected = inputs.capture(python, allow_links=True)
    result = Intent(build, runtime, selected, inputs.capture(selected.resolved),
        tuple(inputs.capture(path) for path in producer_paths(build.intent.source.intent.sdk.root)),
        inputs.capture(policy_file, keep=True, maximum=inputs.MAX_RECORD),
        encoded(rust_source_build.policy(policy)), plain, arguments, wait_ms)
    result.verify()
    require(not runtime.exists() and not runtime.is_symlink(), 'Rust prepared runtime must be new')
    return result


def expected(intent: Intent, launch_id: object) -> tuple[dict, dict, dict]:
    """Only the validated SDK-generated nonce is learned from preparation output."""
    require(type(launch_id) is str and re.fullmatch('[a-f0-9]{32}', launch_id) is not None,
            'invalid Rust preparation launch identity')
    request = {'schema_version': 1, 'kind': 'otelc.rust.request', 'profile': owned.PROFILE,
        'build': dict(intent.build.files)[owned.MANIFEST].gate_identity(), 'runtime': str(intent.runtime),
        'policy': intent.policy(), 'arguments': list(intent.arguments), 'plain': intent.plain,
        'wait_ms': intent.wait_ms, 'launch_id': launch_id}
    image = intent.image()
    plan = {'schema_version': 1, 'kind': 'otelc.rust.plan', 'profile': owned.PROFILE,
        'request_sha256': digest(request), 'cwd': str(intent.source().intent.project),
        'argv': [str(image.path), *intent.arguments], 'image': image.gate_identity(), 'source_complete': False}
    prepared = {'schema_version': 1, 'kind': 'otelc.rust.prepared', 'profile': owned.PROFILE,
        'request_sha256': digest(request), 'plan_sha256': digest(plan),
        'interpreter': intent.interpreter.gate_identity(), 'interpreter_spelling': str(intent.python.path),
        'producer': [file.gate_identity() for file in intent.producer], 'source_complete': False}
    return request, plan, prepared


@dataclass(frozen=True)
class Prepared:
    """Original private records stay bound across later owned application execution."""

    intent: Intent
    records: tuple[inputs.Record, ...]
    directory_facts: tuple

    def value(self, name: str) -> dict:
        """Decode a fixed original record without handing out mutable accepted data."""
        require(type(name) is str and name in RECORDS, 'unknown Rust preparation record')
        return next(record.value() for record in self.records if record.file.path.name == name)

    def verify(self) -> None:
        """Rehash original facts and independently reconstructed request/plan/prepared data."""
        require(type(self.intent) is Intent, 'Rust preparation is missing caller intent')
        self.intent.verify()
        require(inputs.directory(self.intent.runtime) == self.directory_facts
                and type(self.records) is tuple and len(self.records) == 3
                and all(type(record) is inputs.Record for record in self.records)
                and tuple(record.file.path for record in self.records)
                    == tuple(self.intent.runtime / name for name in RECORDS),
                'Rust original preparation directory or record denominator changed')
        for record in self.records:
            record.verify()
        request = self.value(REQUEST)
        values = expected(self.intent, request.get('launch_id'))
        require(all(same(self.value(name), value) for name, value in zip(RECORDS, values)),
                'Rust preparation records differ from fixed caller intent')


def read(intent: Intent) -> Prepared:
    """Accept all three stable publications before any supervisor/application starts."""
    require(type(intent) is Intent, 'Rust preparation reader needs pre-prepare caller intent')
    intent.verify()
    directory = inputs.directory(intent.runtime)
    records = tuple(inputs.published(intent.runtime / name) for name in RECORDS)
    require({path.name for path in intent.runtime.iterdir()} == set(RECORDS),
            'Rust runtime was used or contaminated before preparation acceptance')
    result = Prepared(intent, records, directory)
    result.verify()
    return result


def command(prepared: Prepared) -> list[str]:
    """Only an accepted, unused preparation can select the fixed isolated supervisor."""
    require(type(prepared) is Prepared, 'Rust supervisor command requires accepted preparation')
    prepared.verify()
    intent = prepared.intent
    require(not any((intent.runtime / name).exists() or (intent.runtime / name).is_symlink()
                    for name in ('rust-supervisor-start.json', 'rust-application-start.json')),
            'Rust prepared execution is single-use')
    return supervisor_argv(intent)


def supervisor_argv(intent: Intent) -> list[str]:
    """Reconstruct the same fixed invocation for pre-start and later ownership checks."""
    require(type(intent) is Intent, 'Rust supervisor argv requires frozen caller intent')
    intent.verify()
    return [str(intent.python.path), '-I', '-S',
            str(intent.source().intent.sdk.root / 'otelc/rust_supervisor.py'), str(intent.runtime)]
