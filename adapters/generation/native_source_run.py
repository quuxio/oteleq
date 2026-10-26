"""Connect generated native callers to fixed SDK builds and owned applications."""

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import tomllib

import native_prepared
import native_inputs
import native_lifetime_build
import native_lifetime_caller
import native_lifetime_frontend
import native_lifetime_intent
import native_lifetime_policy
import native_lifetime_receipt
import native_frontend
import native_profile
from native_protocol import require, same
import native_session
import native_source
import native_unit_build
import native_unit_caller
import native_telemetry
import native_live
import native_control_receipt
import sequences


@dataclass(frozen=True)
class Run:
    """Keep caller/compiler intent and the actual owned execution together."""

    caller: native_unit_caller.Caller | native_lifetime_caller.Caller
    prepared: native_prepared.Prepared
    session: native_session.Session
    execute: Callable
    lifetimes: native_lifetime_intent.Intent | None = None
    frontend: native_lifetime_frontend.Context | None = None
    expected_before_build: native_inputs.Record | None = None
    controls: native_live.Session | None = None

    def verify(self, folder: Path) -> None:
        """Repeat semantic input checks after execution, preserving original facts."""
        self.caller.verify()
        self.prepared.verify()
        if self.frontend is not None:
            self.frontend.verify()
        if self.expected_before_build is not None:
            self.expected_before_build.verify()
        if self.lifetimes is not None:
            self.lifetimes.verify()
        require(self.session.execution is not None, 'native worker lacks owned completion')
        self.session.execution.verify()
        if self.controls is not None:
            require(self.controls.entry_json == self.caller.source.entry_json,
                    'native controls differ from frozen compiler caller inputs')
            self.controls.verify()
        self.caller.recheck(folder / 'native-after-execution-inputs', self.execute)

    def witness(self, bodies: list, service: str, roots: tuple[str, ...], folder: Path):
        """Keep function-only and independently declared lifetime receipts distinct."""
        if self.controls is not None:
            return native_control_receipt.witness(self.session.execution, self.controls, bodies, service, roots, folder)
        if self.lifetimes is None:
            return native_telemetry.witness(self.session.execution, bodies, service, roots, folder=folder)
        require(self.lifetimes.roots == roots and service == self.prepared.intent.policy()['resource']['service_name'],
                'native lifetime receipt has another function or service')
        verified = native_lifetime_receipt.witness(self.session.execution, self.lifetimes, bodies)
        if verified is None:
            return None
        (folder / 'native-verified-lifetimes.json').write_text(json.dumps(verified, indent=2, allow_nan=False) + '\n')
        result = {name: verified[name] for name in native_telemetry.WITNESS_FIELDS}
        # The common comparator counts selected function spans. The separate
        # receipt retains and validates every lifetime span and SDK unit.
        result['spans'] = sum(verified['functions'].values())
        return result


def prepare(workflow, workspace: Path, data: dict, entry: dict, case: dict, project: Path,
            tools: dict, environment: dict, folder: Path, config: Path, lane: str, *, bodies: list | None = None) -> Run:
    """Freeze every caller input before invoking the public producer commands."""
    require(native_source.enabled(entry) and lane in ('baseline', 'instrumented_on'), 'invalid prepared native lane')
    root = Path(data['otelc_root'])
    language = entry['language']
    options = entry['native_options']
    kind = native_lifetime_policy.kind(entry)
    declarations = None
    if kind is not None:
        native_lifetime_policy.require_expectations(entry)
        declarations = native_lifetime_policy.expectations(case.get(native_lifetime_policy.EXPECTATIONS), language)
        require(same(declarations, entry[native_lifetime_policy.EXPECTATIONS]),
                'native lifetime case differs from the frozen fixture contract')
    profile = data['native_projects'][language]
    native_profile.directories(project, {language: profile})
    retained = workspace / native_profile.DIRECTORY / language
    timeout = options['build_timeout_ms'] / 1000
    count = 0

    def execute(argv, cwd):
        nonlocal count
        destination = folder / 'native-tooling' / str(count)
        count += 1
        destination.mkdir(mode=0o700, parents=True)
        workflow.write(destination / 'command.json', {'argv': list(map(str, argv)), 'cwd': str(cwd),
                                                     'timeout_ms': options['build_timeout_ms']})
        result = workflow.execute(argv, cwd, environment, destination, timeout=timeout,
                                  max_output_bytes=native_frontend.MAX_METADATA_BYTES)
        require(result.returncode == 0, 'native public build/preparation failed; inspect retained compiler channels')
        return result

    sdk = native_source.sdk(root, language, tools, options, folder, execute)
    policy = tomllib.loads(config.read_text())
    source = native_unit_caller.freeze(sdk, project, profile, retained, entry, case['arguments'], policy)
    frontend = expected_record = None
    observations = None
    if kind is None:
        caller = native_unit_caller.prepare(source, folder / 'helpers', folder / 'native-caller',
                                            folder / 'native-build', execute)
        context = caller.intent
    else:
        frontend = native_lifetime_frontend.prepare(source, kind, folder / 'native-lifetime-tool', execute)
        caller = native_lifetime_caller.prepare(source, folder / 'helpers', folder / 'native-caller',
                                                folder / 'native-build', frontend.tool, execute)
        context = caller.intent.base
        observations = native_lifetime_policy.resolve(caller.intent, declarations)
        expected_record = native_session.publish(folder / 'expected-lifetimes-before-build.json', {
            'schema_version': 1, 'kind': 'oteleq.native.lifetime-before-build',
            'roots': [entry['otelc_runtime_function']], 'observations': [row.data() for row in observations]})
    recipe = folder / 'native-recipe.json'
    workflow.write(recipe, context.recipe())
    execute(native_source.cli(root, tools) + ['--config', config, 'native-build', '--language', language,
        '--root', project, '--recipe', recipe, '--output', context.output, '--sdk-build', sdk.directory], root)
    caller.verify()
    if frontend is not None:
        frontend.verify()
        expected_record.verify()
    build = (native_unit_build.read(caller.intent) if kind is None else native_lifetime_build.read(caller.intent))
    caller.recheck(folder / 'native-after-build-inputs', execute)
    workflow.write(folder / workflow.BUILD_IDENTITIES,
                   {'profile': native_source.BACKEND, 'recipe': context.recipe(),
                    'plain': build.file('plain').gate_identity(),
                    'instrumented': build.file('instrumented').gate_identity()})
    intent = native_prepared.freeze(build, folder / 'native-runtime', tools['python-host'], config,
                                    policy, plain=lane == 'baseline')
    command = native_source.cli(root, tools) + ['--config', config, 'native-run', '--build', context.output,
        '--runtime', intent.runtime, '--prepare-only']
    if lane == 'baseline':
        command.append('--plain')
    execute(command, root)
    launch = native_prepared.read(intent)
    caller.verify()
    expectations = None
    if observations is not None:
        expected_record.verify()
        frontend.verify()
        expectations = native_lifetime_intent.freeze(launch, folder / 'expected-lifetimes.json',
            (entry['otelc_runtime_function'],), observations)
    controls = None
    if sequences.controls(entry):
        controls = native_live.Session(launch, folder, entry, case['sequence'], case['arguments'], bodies,
                                      data['configuration']['limits']['max_capture_bytes'])
    owner = native_session.Session(launch, **({'controls': controls} if controls is not None else {}))
    return Run(caller, launch, owner, execute, expectations, frontend, expected_record, controls)
