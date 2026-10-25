"""Check native preparation against caller intent without importing the SDK."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tomllib

import native_build
import native_inputs as inputs
from native_protocol import PROFILE, digest, encoded, require, same
from otelc_capture import strict_json

REQUEST, PLAN, PREPARED = 'native-request.json', 'native-plan.json', 'native-prepared.json'
START_FILES = ('native-supervisor-start.json', 'native-application-start.json')
EXECUTION_FILES = (*START_FILES, 'native-host-release.json', 'native-execution.json', 'app')
REQUIRED = {'__init__.py', '__main__.py', 'cli_bootstrap.py', 'config.py', 'file_inputs.py', 'health.py',
            'llvm_backend.py', 'native_build.py', 'native_gate.py', 'native_launch.py',
            'native_supervisor.py', 'prepared_native.py', 'python_launch_files.py', 'python_sdk_io.py'}


def producer_paths(root: Path) -> tuple[Path, ...]:
    """Select fixed SDK producer sources before reading preparation metadata."""
    paths = tuple(sorted((root / 'otelc').glob('*.py')))
    require(REQUIRED <= {path.name for path in paths} and len(paths) <= 4096, 'incomplete native SDK producer installation')
    return paths


@dataclass(frozen=True)
class Intent:
    """Runtime policy, literal arguments and all SDK source paths precede preparation."""

    build: native_build.Build
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
        """Return an unaliased copy of the frozen runtime policy."""
        return strict_json(self.policy_json)

    def verify(self) -> None:
        """Keep build, policy file, interpreter and producer sources unchanged."""
        self.build.verify()
        self.python.verify()
        self.interpreter.verify()
        self.policy_file.verify()
        require(same(tomllib.loads(self.policy_file.content.decode()), self.policy()), 'native runtime policy bytes differ from intent')
        require(tuple(item.path for item in self.producer) == producer_paths(self.build.intent.sdk.root),
                'native SDK producer source set changed')
        for item in self.producer:
            item.verify()


def freeze(build: native_build.Build, runtime: Path, python: Path, policy_file: Path,
           policy: dict, *, plain: bool, arguments: tuple[str, ...] = (), wait_ms: int = 30000) -> Intent:
    """Capture bounded literal intent before the SDK creates launch records."""
    require(type(build) is native_build.Build and type(plain) is bool and type(wait_ms) is int
            and 1 <= wait_ms <= 300000, 'invalid native lane, build or release budget')
    build.verify()
    require(type(arguments) is tuple and len(arguments) <= 4096
            and all(type(value) is str and '\0' not in value for value in arguments)
            and sum(len(os.fsencode(value)) for value in arguments) <= 1024 * 1024, 'invalid literal native arguments')
    require(runtime.is_absolute() and runtime == runtime.resolve() and runtime.parent == runtime.parent.resolve(strict=True)
            and not runtime.exists() and not runtime.is_symlink()
            and not any(runtime.is_relative_to(path) for path in (build.intent.project, build.intent.output, build.intent.sdk.root)),
            'native runtime must be a new canonical external directory')
    initial = build.intent.policy()
    require(type(policy) is dict and same(policy.get('schema_version'), 3)
            and type(policy.get('languages')) is list and build.intent.language in policy['languages']
            and same({key: policy[key] for key in ('sources', 'functions')},
                     {key: initial[key] for key in ('sources', 'functions')})
            and type(policy.get('lifetimes')) is dict and policy['lifetimes'].get('enabled') is False
            and same(policy.get('context'), {'tasks': False, 'http': False}), 'native runtime policy differs from compiled selection')
    host = inputs.capture(python, allow_links=True)
    result = Intent(build, runtime, host, inputs.capture(host.resolved),
        tuple(inputs.capture(path) for path in producer_paths(build.intent.sdk.root)),
        inputs.capture(policy_file, keep=True), encoded(policy), plain, arguments, wait_ms)
    result.verify()
    return result


def command(intent: Intent) -> list[str]:
    """Only the fixed isolated SDK supervisor can own this prepared application."""
    return [str(intent.python.path), '-I', '-S', str(intent.build.intent.sdk.root / 'otelc/native_supervisor.py'), str(intent.runtime)]


@dataclass(frozen=True)
class Prepared:
    """Original snapshots retain all three private preparation records."""
    intent: Intent
    records: tuple[inputs.Record, ...]
    directory_facts: tuple

    def value(self, name: str) -> dict:
        """Decode a fixed record as a fresh primitive object."""
        require(name in (REQUEST, PLAN, PREPARED), 'unknown native preparation record')
        return next(record.value() for record in self.records if record.file.path.name == name)

    def verify(self) -> None:
        """Recheck original preparation identities without recertifying edits."""
        self.intent.verify()
        require(inputs.directory(self.intent.runtime) == self.directory_facts
                and len(self.records) == 3
                and {record.file.path for record in self.records} ==
                    {self.intent.runtime / name for name in (REQUEST, PLAN, PREPARED)}, 'native preparation binding changed')
        for record in self.records:
            record.verify()


def read(intent: Intent) -> Prepared:
    """SDK-generated launch identity is bound before either application lane starts."""
    intent.verify()
    directory = inputs.directory(intent.runtime)
    require({path.name for path in intent.runtime.iterdir()} == {REQUEST, PLAN, PREPARED}, 'native runtime was used before preparation acceptance')
    records = tuple(inputs.read(intent.runtime / name, private=True) for name in (REQUEST, PLAN, PREPARED))
    request, plan, prepared = (record.value() for record in records)
    launch_id = request.get('launch_id')
    require(type(launch_id) is str and re.fullmatch('[0-9a-f]{32}', launch_id) is not None, 'invalid native launch identity')
    expected_request = {'schema_version': 1, 'kind': 'otelc.native.request', 'profile': PROFILE,
        'build': intent.build.file(native_build.MANIFEST).gate_identity(), 'runtime': str(intent.runtime),
        'policy': intent.policy(), 'arguments': list(intent.arguments), 'plain': intent.plain,
        'wait_ms': intent.wait_ms, 'launch_id': launch_id}
    require(same(request, expected_request), 'native request differs from caller intent')
    name = 'plain' if intent.plain else 'instrumented'
    image = intent.build.file(name)
    expected_plan = {'schema_version': 1, 'kind': 'otelc.native.plan', 'profile': PROFILE,
        'request_sha256': digest(expected_request), 'cwd': str(intent.build.intent.project),
        'argv': [str(image.path), *intent.arguments], 'image': image.gate_identity(), 'source_complete': False}
    require(same(plan, expected_plan), 'native plan differs from the fixed lane and arguments')
    expected_prepared = {'schema_version': 1, 'kind': 'otelc.native.prepared', 'profile': PROFILE,
        'request_sha256': digest(expected_request), 'plan_sha256': digest(expected_plan),
        'interpreter': intent.interpreter.gate_identity(), 'interpreter_spelling': str(intent.python.path),
        'producer': [item.gate_identity() for item in intent.producer], 'source_complete': False}
    require(same(prepared, expected_prepared), 'native preparation differs from the fixed interpreter or producer')
    result = Prepared(intent, records, directory)
    result.verify()
    return result
