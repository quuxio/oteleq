"""Connect generated native callers to fixed SDK builds and owned applications."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import tomllib

import native_prepared
import native_frontend
import native_profile
from native_protocol import require
import native_session
import native_source
import native_unit_build
import native_unit_caller


@dataclass(frozen=True)
class Run:
    """Keep caller/compiler intent and the actual owned execution together."""

    caller: native_unit_caller.Caller
    prepared: native_prepared.Prepared
    session: native_session.Session
    execute: Callable

    def verify(self, folder: Path) -> None:
        """Repeat semantic input checks after execution, preserving original facts."""
        self.caller.verify()
        self.prepared.verify()
        require(self.session.execution is not None, 'native worker lacks owned completion')
        self.session.execution.verify()
        self.caller.recheck(folder / 'native-after-execution-inputs', self.execute)


def prepare(workflow, workspace: Path, data: dict, entry: dict, case: dict, project: Path,
            tools: dict, environment: dict, folder: Path, config: Path, lane: str) -> Run:
    """Freeze every caller input before invoking the public producer commands."""
    require(native_source.enabled(entry) and lane in ('baseline', 'instrumented_on'), 'invalid prepared native lane')
    root = Path(data['otelc_root'])
    language = entry['language']
    options = entry['native_options']
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
    caller = native_unit_caller.prepare(source, folder / 'helpers', folder / 'native-caller',
                                        folder / 'native-build', execute)
    recipe = folder / 'native-recipe.json'
    workflow.write(recipe, caller.intent.recipe())
    execute(native_source.cli(root, tools) + ['--config', config, 'native-build', '--language', language,
        '--root', project, '--recipe', recipe, '--output', caller.intent.output, '--sdk-build', sdk.directory], root)
    caller.verify()
    build = native_unit_build.read(caller.intent)
    caller.recheck(folder / 'native-after-build-inputs', execute)
    workflow.write(folder / workflow.BUILD_IDENTITIES,
                   {'profile': native_source.BACKEND, 'recipe': caller.intent.recipe(),
                    'plain': build.file('plain').gate_identity(),
                    'instrumented': build.file('instrumented').gate_identity()})
    intent = native_prepared.freeze(build, folder / 'native-runtime', tools['python-host'], config,
                                    policy, plain=lane == 'baseline')
    command = native_source.cli(root, tools) + ['--config', config, 'native-run', '--build', build.intent.output,
        '--runtime', intent.runtime, '--prepare-only']
    if lane == 'baseline':
        command.append('--plain')
    execute(command, root)
    launch = native_prepared.read(intent)
    caller.verify()
    return Run(caller, launch, native_session.Session(launch), execute)
