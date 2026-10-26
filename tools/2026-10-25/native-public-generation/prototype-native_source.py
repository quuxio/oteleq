"""Select the explicit standalone native provider and bind compiler-owned discovery."""

import os
from pathlib import Path
import subprocess
import sys

import cpp_models
import discovery
import native_frontend
import native_inputs
import native_prepared
import native_project
import native_protocol
import native_sdk
import otelc_capture as capture

BACKEND = 'prepared'
DIRECTORY = 'native-source'
BUILD_TIMEOUT = 180000
LANGUAGES = ('c', 'cpp')


def settings(value: dict) -> dict:
    """Keep legacy native recipes unchanged; prepared builds are explicit."""
    allowed = {'compilation_database', 'targets', 'backend', 'profile', 'sdk_build', 'build_timeout_ms'}
    native_protocol.require(type(value) is dict and not set(value) - allowed, 'unsupported native adapter settings')
    project = native_project.settings({name: value[name] for name in ('compilation_database', 'targets') if name in value})
    backend = value.get('backend', 'legacy')
    native_protocol.require(type(backend) is str and backend in ('legacy', BACKEND), 'native backend must be legacy or prepared')
    if backend == 'legacy':
        native_protocol.require(not set(value) & {'profile', 'sdk_build', 'build_timeout_ms'},
                                'native prepared settings require backend=prepared')
        return project
    native_protocol.require(value.get('profile', native_protocol.PROFILE) == native_protocol.PROFILE,
                            'unsupported native prepared profile')
    sdk_build = value.get('sdk_build')
    if sdk_build is not None:
        native_protocol.require(type(sdk_build) is str and bool(sdk_build) and '\0' not in sdk_build
                                and Path(sdk_build).is_absolute() and '..' not in Path(sdk_build).parts,
                                'native sdk_build requires an absolute caller-selected directory')
    timeout = value.get('build_timeout_ms', BUILD_TIMEOUT)
    native_protocol.require(type(timeout) is int and 1000 <= timeout <= 900000, 'invalid native build timeout')
    native_protocol.require(project['compilation_database'] is None,
        'prepared compilation-database targets require the separately versioned SDK unit/driver recipe contract')
    return {**project, 'backend': BACKEND, 'profile': native_protocol.PROFILE,
            'sdk_build': sdk_build, 'build_timeout_ms': timeout}


def enabled(entry: dict) -> bool:
    """Only the explicitly selected C/C++ profile uses native owned execution."""
    return entry.get('language') in LANGUAGES and entry.get('native_backend') == BACKEND


def selected(options: dict) -> bool:
    """Planning must choose this route before legacy SDK metadata is accessed."""
    return options.get('backend') == BACKEND


def configure(entry: dict, options: dict) -> None:
    """Retain operator settings in the sealed inventory, without inferring support."""
    if entry['language'] in LANGUAGES and selected(options):
        entry.update(native_backend=BACKEND, native_profile=native_protocol.PROFILE, native_options=options)


def selected_tools(root: Path, language: str) -> dict:
    """Metadata cannot select a compiler, interpreter or helper executable."""
    native_protocol.require(language in LANGUAGES, 'native tools require c or cpp')
    name = 'clang' if language == 'c' else 'clang++'
    variable = 'OTELC_CLANG' if language == 'c' else 'OTELC_CLANGXX'
    default = '/opt/homebrew/opt/llvm@22/bin' if sys.platform == 'darwin' else '/usr/lib/llvm-22/bin'
    config = capture.tool_path(os.environ.get('LLVM_CONFIG', default + '/llvm-config'))
    compiler = capture.tool_path(os.environ.get(variable, str(config.parent / name)))
    result = {name: compiler, 'llvm-config': config, 'python-host': Path(sys.executable).absolute(),
              'cmake': capture.tool_path('cmake'), 'ninja': capture.tool_path('ninja')}
    if language == 'cpp':
        result['cpp-demangler'] = capture.tool_path(str(config.parent / 'llvm-cxxfilt'))
    return result


def sdk_directory(root: Path, options: dict) -> Path:
    """Only operator configuration or this fixed default chooses SDK products."""
    return Path(options['sdk_build']) if options['sdk_build'] is not None else root / 'build/prepared-sdk'


def artefacts(root: Path, language: str, tools: dict, options: dict) -> dict:
    """Freeze the complete selected native route and original file/alias facts."""
    native_protocol.require(root.is_absolute() and root.resolve(strict=True) == root and language in LANGUAGES,
                            'native provider root must be canonical')
    directory = sdk_directory(root, options)
    library = 'libotelc_native_runtime.dylib' if sys.platform == 'darwin' else 'libotelc_native_runtime.so'
    paths = {*native_sdk.source_paths(root), *native_prepared.producer_paths(root),
             root / 'native/llvm/OtelcPass.cpp', root / 'adapters/native/gate/ExecGate.c',
             directory / 'native-sdk-build.json', directory / library}
    result = {}
    for path in sorted(paths):
        held = native_inputs.capture(path)
        result[str(path)] = {'identity': held.gate_identity(), 'path_facts': list(held.path_facts)}
    for path in tools.values():
        held = native_inputs.capture(path, allow_links=True)
        result[str(path)] = {'identity': held.gate_identity(), 'path_facts': list(held.path_facts)}
    return {'profile': native_protocol.PROFILE, 'files': result}


def stable(root: Path, language: str, tools: dict, options: dict, expected: dict) -> None:
    """Recompute fixed path sets; producer metadata cannot redirect a preservation read."""
    native_protocol.require(native_protocol.same(artefacts(root, language, tools, options), expected),
                            'native provider inputs or original file facts changed')


def cli(root: Path, tools: dict) -> list:
    """Select the installed public Python dispatcher with isolated no-site startup."""
    return [tools['python-host'], '-I', '-S', '-B', root / 'otelc/cli_bootstrap.py']


def flags(language: str, project: Path) -> list[str]:
    """Match the fixed SDK build recipe, including C11 and optimisation macros."""
    native_protocol.require(language in LANGUAGES, 'invalid native discovery language')
    return ['-O2', '-g', '-fexceptions', '-pthread', '-std=c11' if language == 'c' else '-std=c++17',
            '-I', str(project)]


def discover(path: Path, language: str, workspace: Path, tools: dict, execute, cache: dict) -> dict:
    """Use the maintained matched Clang frontend before any SDK application build."""
    project = workspace / 'snapshot'
    native_protocol.require(path.is_relative_to(project) and path.resolve(strict=True) == path,
                            'native discovery source is not in the private snapshot')
    compiler = tools['clang' if language == 'c' else 'clang++']
    retained = workspace / DIRECTORY / language
    if language not in cache:
        cache[language] = native_frontend.build(compiler, retained / 'frontend', project, execute)
    record = cache[language]
    name = path.relative_to(project).as_posix()
    key = capture.digest(name.encode())
    unit = {'source': name, 'directory': '.', 'compiler': str(compiler),
            'flags': [*flags(language, project), '-x', 'c' if language == 'c' else 'c++']}
    document = native_frontend.inspect(unit, project, record, retained / 'frontend',
                                       retained / 'units' / key, execute)
    state = native_frontend.input_state(document, unit, project)
    value = discovery.native_inventory(document['ast'], path, cpp=language == 'cpp')
    if language == 'cpp':
        cpp_models.bind_symbols(value, tools['cpp-demangler'], project, execute)
    value.update(native_source_inputs=state, native_source_unit=unit,
                 native_source_frontend=record, native_source_evidence=key)
    return value
