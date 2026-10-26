"""Select explicit compiler-bound native builds without importing SDK renderers."""

import hashlib
import json
import os
from pathlib import Path
import sys

import native_inputs
import native_lifetime_policy as lifetimes
import native_prepared
import native_project
import native_protocol
import native_sdk
import native_toolchain
from native_protocol import require
import otelc_capture as capture

BACKEND = 'prepared'
DIRECTORY = 'native-source'
BUILD_TIMEOUT = 180000
LANGUAGES = ('c', 'cpp')


def standalone_targets(language: str, compiler: Path, contents: dict) -> list[dict]:
    """Fixed standalone units stay separate; linked projects require explicit targets."""
    names = sorted(name for name in contents if Path(name).suffix in native_project.EXTENSIONS[language])
    native_protocol.require(1 <= len(names) <= 256, 'prepared native standalone source needs 1 to 256 units')
    flags = ['-O2', '-fexceptions', '-pthread', '-std=c11' if language == 'c' else '-std=c++17', '-I', '.']
    return [{'name': 'unit_' + hashlib.sha256(name.encode()).hexdigest()[:20],
             'units': [{'source': name, 'directory': '.', 'flags': flags.copy(),
                        'output': 'unit_' + str(index) + '.o', 'compiler': str(compiler), 'language': language}],
             'link_flags': ['-pthread']}
            for index, name in enumerate(names)]


def settings(value: dict) -> dict:
    """Freeze explicit provider selection while preserving default native recipes."""
    allowed = {'compilation_database', 'targets', 'backend', 'profile', 'sdk_build', 'build_timeout_ms', 'lifetimes', 'sdk_source_profile'}
    native_protocol.require(type(value) is dict and not set(value) - allowed, 'unsupported native adapter settings')
    project = native_project.settings({name: value[name] for name in ('compilation_database', 'targets') if name in value})
    backend = value.get('backend', 'legacy')
    native_protocol.require(type(backend) is str and backend in ('legacy', BACKEND), 'native backend must be legacy or prepared')
    if backend == 'legacy':
        native_protocol.require(not set(value) & {'profile', 'sdk_build', 'build_timeout_ms', 'lifetimes', 'sdk_source_profile'},
                                'native prepared settings require backend=prepared')
        return project
    profile = value.get('profile', native_protocol.PROFILE)
    native_protocol.require(type(profile) is str and profile in (native_protocol.PROFILE, *lifetimes.PROFILES),
                            'unsupported native prepared profile')
    life = lifetimes.options(value.get('lifetimes')) if profile in lifetimes.PROFILES else None
    native_protocol.require(life is not None or 'lifetimes' not in value,
                            'native lifetime settings require their explicit profile')
    directory = value.get('sdk_build')
    if directory is not None:
        native_protocol.require(type(directory) is str and bool(directory) and '\0' not in directory
                                and Path(directory).is_absolute() and '..' not in Path(directory).parts,
                                'native sdk_build requires an absolute caller-selected directory')
    timeout = value.get('build_timeout_ms', BUILD_TIMEOUT)
    native_protocol.require(type(timeout) is int and 1000 <= timeout <= 900000, 'invalid native build timeout')
    result = {**project, 'backend': BACKEND, 'profile': profile,
            'sdk_build': directory, 'build_timeout_ms': timeout,
            **({'lifetimes': life} if life is not None else {})}
    if 'sdk_source_profile' in value:
        result['sdk_source_profile'] = value['sdk_source_profile']
        source_profile(result)
    return result


def selected(options: dict) -> bool:
    """Only explicit operator configuration selects the new native contract."""
    return options.get('backend') == BACKEND


def enabled(entry: dict) -> bool:
    """A language name alone cannot change the native execution provider."""
    return entry.get('language') in LANGUAGES and entry.get('native_backend') == BACKEND


def configure(entry: dict, options: dict) -> None:
    """Bind source selection separately from demangled names and emitted labels."""
    if entry['language'] in LANGUAGES and selected(options):
        entry.update(native_backend=BACKEND, native_options=options,
                     otelc_runtime_function=entry['path'] + '::' + entry['otelc_function'])
        lifetimes.kind(entry)


def build_version(options: dict) -> int:
    """Each explicit profile negotiates its own source-build contract."""
    profile = options.get('profile', native_protocol.PROFILE)
    require(type(profile) is str and profile in (native_protocol.PROFILE, *lifetimes.PROFILES),
            'unsupported native prepared profile')
    return lifetimes.PROFILES[profile][2] if profile in lifetimes.PROFILES else 3


def source_profile(options: dict) -> str:
    """Select a caller-declared ABI source closure without enabling extra features."""
    build_version(options)
    lifetime = options.get('profile') in lifetimes.PROFILES
    selected = options.get('sdk_source_profile', 'resource-v1' if lifetime else 'function-v2')
    require(type(selected) is str and selected in ('function-v2', 'resource-v1')
            and (not lifetime or selected == 'resource-v1'), 'incompatible native SDK source profile')
    return selected


def selected_tools(root: Path, language: str) -> dict:
    """The operator chooses tools before any producer metadata is read."""
    native_protocol.require(language in LANGUAGES, 'native tools require c or cpp')
    default = '/opt/homebrew/opt/llvm@22/bin' if sys.platform == 'darwin' else '/usr/lib/llvm-22/bin'
    config = capture.tool_path(os.environ.get('LLVM_CONFIG', default + '/llvm-config'))
    result = {'llvm-config': config, 'python-host': Path(sys.executable).absolute(),
              'cmake': capture.tool_path('cmake'), 'ninja': capture.tool_path('ninja'),
              'llvm-objcopy': capture.tool_path(str(config.parent / 'llvm-objcopy'))}
    for name, variable in (('clang', 'OTELC_CLANG'), ('clang++', 'OTELC_CLANGXX')):
        result[name] = capture.tool_path(os.environ.get(variable, str(config.parent / name)))
    if language == 'cpp':
        result['cpp-demangler'] = capture.tool_path(str(config.parent / 'llvm-cxxfilt'))
    return result


def sdk_directory(root: Path, options: dict) -> Path:
    """Provider output paths come only from frozen operator settings."""
    return Path(options['sdk_build']) if options['sdk_build'] is not None else root / 'build/prepared-sdk'


def artefacts(root: Path, language: str, tools: dict, options: dict) -> dict:
    """Preserve original source/product/tool bytes and physical file identities."""
    native_protocol.require(root.is_absolute() and root.resolve(strict=True) == root and language in LANGUAGES,
                            'native provider root must be canonical')
    directory = sdk_directory(root, options)
    library = 'libotelc_native_runtime.dylib' if sys.platform == 'darwin' else 'libotelc_native_runtime.so'
    paths = {*native_sdk.source_paths(root, source_profile=source_profile(options)), *native_prepared.producer_paths(root),
             root / 'native/llvm/OtelcPass.cpp', root / 'adapters/native/gate/ExecGate.c',
             directory / 'native-sdk-build.json', directory / library}
    extra_tools = []
    if options.get('profile') in lifetimes.PROFILES:
        kind = lifetimes.PROFILES[options['profile']][0]
        stem = 'Object' if kind == 'object' else 'Resource'
        paths.update((root / 'native/llvm' / (stem + 'Pass.cpp'),
                      root / 'native/llvm' / (kind + '_pass.h'),
                      root / 'native/clang' / ('Lifetimes.cpp' if kind == 'object' else 'Resources.cpp')))
        if kind == 'resource':
            extra_tools.append(tools['llvm-config'].parent / 'llvm-nm')
    result = {}
    for path in sorted(paths):
        held = native_inputs.capture(path)
        result[str(path)] = {'identity': held.gate_identity(), 'path_facts': list(held.path_facts)}
    for path in (*tools.values(), *extra_tools):
        held = native_inputs.capture(path, allow_links=True)
        result[str(path)] = {'identity': held.gate_identity(), 'path_facts': list(held.path_facts)}
    return {'profile': options.get('profile', native_protocol.PROFILE), 'files': result}


def stable(root: Path, language: str, tools: dict, options: dict, expected: dict) -> None:
    """Re-enumerate fixed inputs rather than following producer-selected paths."""
    native_protocol.require(native_protocol.same(artefacts(root, language, tools, options), expected),
                            'native provider inputs or original file facts changed')


def sdk(root: Path, language: str, tools: dict, options: dict, folder: Path, execute) -> native_sdk.SDK:
    """Read one caller-selected SDK against independently queried LLVM recipes."""
    compiler = tools['clang' if language == 'c' else 'clang++']
    toolchain = native_toolchain.capture(tools['llvm-config'], compiler, language, folder, execute)
    selected = source_profile(options)
    extra = {'source_profile': selected} if selected != 'function-v2' else {}
    return native_sdk.capture(root, sdk_directory(root, options), toolchain, cmake=tools['cmake'], ninja=tools['ninja'], **extra)


def cli(root: Path, tools: dict) -> list:
    """Only the fixed isolated public dispatcher can build or prepare native code."""
    return [tools['python-host'], '-I', '-S', '-B', root / 'otelc/cli_bootstrap.py']


def negotiate(workflow, root: Path, workspace: Path, language: str, tools: dict, options: dict, execute) -> None:
    """The selected build3/4/5 descriptor must be established before generation."""
    folder = workspace / DIRECTORY / language
    folder.mkdir(parents=True, mode=0o700)
    version = build_version(options)
    command = cli(root, tools) + ['native-protocols', '--build-version', str(version)]
    result = execute(command, root)
    record = {'command': list(map(str, command)), 'status': result.returncode,
              'stdout': result.stdout.decode('utf-8'), 'stderr': result.stderr.decode('utf-8')}
    workflow.write(folder / 'protocols.json', record)
    native_protocol.require(result.returncode == 0, 'public native protocol negotiation failed')
    native_protocol.verify_protocols(capture.strict_json(result.stdout), build_version=version)
    sdk(root, language, tools, options, folder, execute).verify()


def configuration(entry: dict, endpoint: str, service: str) -> dict:
    """Specify every common policy default without importing the producer."""
    native_protocol.require(enabled(entry), 'explicit native entry required')
    native_protocol.require('receiver_fixture' not in entry and 'cpp_receiver' not in entry,
                            'prepared native receivers require separate integration')
    if 'sequence_configuration' in entry:
        import native_sequence
        native_sequence.configuration(entry, entry['sequence_configuration'])
    result = {'schema_version': 3, 'languages': [entry['language']],
            'resource': {'service_name': service},
            'export': {'endpoint': endpoint, 'interval_ms': 1000, 'timeout_ms': 1000, 'shutdown_timeout_ms': 10000},
            'sources': {'include': [entry['path']], 'exclude': []},
            'functions': {'include': [entry['otelc_function']], 'exclude': []},
            'metrics': {'collection': True, 'emission': True,
                        'histogram_boundaries_seconds': [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]},
            'traces': {'enabled': True, 'sample_ratio': 1.0},
            'lifetimes': {'enabled': False, 'include': [], 'exclude': [], 'max_live': 4096, 'release_methods': ['close']},
            'context': {'tasks': False, 'http': False},
            'benchmark': {'iterations': 10000, 'samples': 15, 'warmup': 5}}
    lifetimes.apply(entry, result)
    if 'sequence_configuration' in entry:
        result['metrics'].update(entry['sequence_configuration'][0]['metrics'])
    return result


def policy(entry: dict, endpoint: str, service: str) -> str:
    """Encode the complete common request, including the actual per-attempt service."""
    data = configuration(entry, endpoint, service)
    lines = ['schema_version = 3', 'languages = ' + json.dumps(data['languages'])]
    for name, values in data.items():
        if type(values) is dict:
            lines.append('[' + name + ']')
            lines.extend(key + ' = ' + json.dumps(value, ensure_ascii=True) for key, value in values.items())
    return '\n'.join(lines) + '\n'


def verify_probes(workflow, workspace: Path, data: dict) -> None:
    """Retained selection and protocol evidence remain tied to the original plan."""
    for entry in data['inventory']:
        language = entry['language']
        if language not in LANGUAGES:
            continue
        options = data['configuration']['adapters'].get(language, {})
        native_protocol.require(enabled(entry) == selected(options), 'native backend differs from project policy')
        if enabled(entry):
            native_protocol.require(native_protocol.same(entry.get('native_options'), options)
                and entry.get('otelc_runtime_function') == entry['path'] + '::' + entry['otelc_function'],
                'native entry differs from frozen provider settings')
            native_protocol.require(entry['status'] != 'ready' or 'native_context' in entry,
                                    'ready native entry has no frozen compiler context')
            if lifetimes.kind(entry) is not None and entry['status'] == 'ready':
                lifetimes.require_expectations(entry)
                expected_sources = lifetimes.source_selection(data['native_projects'][language],
                    data['configuration']['sources'], workflow.project_policy.selected)
                native_protocol.require(native_protocol.same(entry.get(lifetimes.SOURCES), expected_sources),
                                        'native lifetime source selection differs from its compiler context')
    directory = workspace / DIRECTORY
    expected = data.get('native_provider_manifest')
    if expected is None:
        native_protocol.require(not directory.exists() and not directory.is_symlink(), 'unowned native provider evidence')
    else:
        native_protocol.require(directory.is_dir() and not directory.is_symlink()
            and workflow.manifest(directory) == expected, 'native provider negotiation evidence changed')
        for language in data['native_projects']:
            options = data['configuration']['adapters'].get(language, {})
            if not selected(options):
                continue
            record = workflow.read(directory / language / 'protocols.json')
            tools = {name: Path(path) for name, path in data['tools'][language].items()}
            version = build_version(options)
            native_protocol.require(record['status'] == 0
                and record['command'] == list(map(str, cli(Path(data['otelc_root']), tools) + ['native-protocols', '--build-version', str(version)])),
                'native protocol command differs from frozen tools')
            native_protocol.verify_protocols(capture.strict_json(record['stdout']), build_version=version)
