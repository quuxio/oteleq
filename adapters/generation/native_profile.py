"""Public native-project planning and immutable copied-root context management."""
from pathlib import Path
import uuid

import discovery
import harness
import native_context
import native_frontend
import native_project
import native_source
import native_workers
import native_workspace
import owned_workspace

DIRECTORY = 'native-context'


def configured(configuration: dict) -> bool:
    """An explicit native recipe can consist entirely of normally excluded files."""
    return any(configuration['adapters'].get(language, {}).get('compilation_database')
               for language in ('c', 'cpp') if language in configuration['languages'])


def prepare_inputs(workflow, source: Path, root: Path, workspace: Path,
                   configuration: dict, contents: dict, *, excluded_files=(), excluded_roots=()) -> tuple[dict, dict]:
    """Retain native discovery failures and bind added inputs before snapshotting."""
    try:
        profiles = prepare(workflow, source, root, workspace, configuration, contents=contents)
        if not profiles:
            return contents, profiles
        required = source_manifest(workflow, source, profiles, excluded_files=excluded_files,
                                   excluded_roots=excluded_roots)
        if any(required.get(name) != digest for name, digest in contents.items()):
            raise ValueError('source changed during native build discovery')
        return required, profiles
    except (ValueError, OSError) as error:
        workflow.write(workspace / 'discovery-failure.json', {'schema_version': workflow.VERSION,
                       'error': str(error), 'phase': 'native build context'})
        raise ValueError(str(error) + '; partial workspace: ' + str(workspace)) from error


def context_manifest(workflow, workspace: Path) -> dict:
    """Compiled tooling has a separate file budget from application source files."""
    return workflow.manifest(workspace / DIRECTORY, max_file_bytes=workflow.MAX_TREE)


def executor(workflow, workspace: Path, root: Path, tools: dict):
    """Compiler inventory writes and temporary files remain in the owned workspace."""
    scratch = workspace / 'scratch'
    scratch.mkdir(parents=True, exist_ok=True)
    environment = workflow.capture.environment(workspace, tools, 'oteleq-native-discovery', root)
    environment.update(HOME=str(scratch), TMPDIR=str(scratch))

    def execute(command, directory, input_data=None):
        return workflow.execute(command, directory, environment, timeout=120, input_data=input_data,
                                max_output_bytes=native_frontend.MAX_METADATA_BYTES)

    return execute


def required_directories(prepared: dict) -> list[str]:
    """Working and explicit include directories can be empty but still required."""
    root = Path(prepared['source_root'])
    paths = set()
    for unit in prepared['units'].values():
        directory = root / unit['directory']
        paths.add(unit['directory'])
        for index, flag in enumerate(unit['flags'][:-1]):
            if flag in native_project.PATH_OPTIONS:
                path = (directory / unit['flags'][index + 1]).resolve()
                if path.is_dir():
                    paths.add(path.relative_to(root).as_posix())
    return sorted(paths)


def capability(workflow, root: Path, retained: Path, execute) -> dict:
    """Freeze interface availability; successful cases still require real witnesses."""
    command = [root / workflow.capture.OTELC_CLI_PATH, 'object', 'rename-main', '--help']
    result = execute(command, retained)
    workflow.write(retained / 'object-transform-request.json', list(map(str, command)))
    (retained / 'object-transform.stdout').write_bytes(result.stdout)
    (retained / 'object-transform.stderr').write_bytes(result.stderr)
    native_project.require(result.returncode == 0 and b'--symbol' in result.stdout and b'rename-main' in result.stdout,
                           'selected SDK does not provide the validated object rename-main interface')
    return {'operation': 'rename-main', 'help_sha256': workflow.capture.file_digest(retained / 'object-transform.stdout')}


def prepare(workflow, source: Path, root: Path, workspace: Path, configuration: dict, *, contents=None) -> dict:
    """Resolve requested native builds before excluded build inputs are snapshotted."""
    profiles = {}
    for language in ('c', 'cpp'):
        options = configuration['adapters'].get(language, {})
        prepared = native_source.selected(options)
        if language not in configuration['languages'] or not (options.get('compilation_database') or prepared):
            continue
        tools = (native_source.selected_tools(root, language) if prepared
                 else workflow.capture.selected_tools(root, language))
        artefacts = (native_source.artefacts(root, language, tools, options) if prepared
                     else workflow.capture.artefacts(root, language, tools))
        selected = tools['clang++' if language == 'cpp' else 'clang']
        retained = workspace / DIRECTORY / language
        execute = executor(workflow, retained, root, tools)
        if prepared:
            native_source.negotiate(workflow, root, workspace, language, tools, options, execute)
            transform = {'operation': 'sdk-unit-recipe1-main-rename'}
        else:
            transform = capability(workflow, root, retained, execute)
        if options.get('compilation_database'):
            project_options = {name: options[name] for name in ('compilation_database', 'targets')}
            profile = native_project.prepare(source, project_options, language, selected, retained, execute)
        else:
            targets = native_source.standalone_targets(language, selected, contents or {})
            profile = native_project.prepare_targets(source, targets, language, selected, retained, execute)
        profile.update(tools={name: str(path) for name, path in tools.items()}, artefacts=artefacts,
                       object_transform=transform)
        profile['directories'] = required_directories(profile)
        profiles[language] = profile
    return profiles


def source_manifest(workflow, source: Path, profiles: dict, *, excluded_files=(), excluded_roots=()) -> dict:
    """Explicit compiler inputs supplement the normal source walk and its budgets."""
    options = {"excluded_files": excluded_files} if excluded_files else {}
    if excluded_roots:
        options["excluded_roots"] = excluded_roots
    contents = workflow.manifest(source, excluded=discovery.IGNORED, **options)
    for profile in profiles.values():
        for name in profile['directories']:
            owned_workspace.require_application_input(source, name)
            path = source / name
            native_project.require(path.is_dir() and path.resolve() == path,
                                   'required directory changed or is a symlink: ' + name)
        for name, expected in profile['local_inputs'].items():
            owned_workspace.require_application_input(source, name)
            path = source / name
            native_project.require(path.is_file() and path.resolve() == path and not path.is_symlink(),
                                   'required input changed or is a symlink: ' + name)
            native_project.require(path.stat().st_size <= workflow.MAX_FILE, 'required input exceeds snapshot limit')
            actual = workflow.capture.file_digest(path)
            native_project.require(actual == expected, 'required compiler input changed: ' + name)
            contents[name] = actual
    native_project.require(len(contents) <= 10000 and
                           sum((source / name).stat().st_size for name in contents) <= workflow.MAX_TREE,
                           'required inputs exceed the source snapshot budget')
    return contents


def directories(project: Path, profiles: dict) -> None:
    """Materialise retained empty working/include directories in a fresh copy."""
    for profile in profiles.values():
        for name in profile['directories']:
            (project / name).mkdir(parents=True, exist_ok=True)


def inventory(workflow, profiles: dict, root: Path, snapshot: Path, workspace: Path, args) -> tuple:
    """Each target/unit variant gets a distinct entry with complete target state."""
    tools, artefacts, entries, covered = {}, {}, [], set()
    for language, profile in profiles.items():
        selected = {name: Path(path) for name, path in profile['tools'].items()}
        tools[language], artefacts[language] = selected, profile['artefacts']
        retained = workspace / DIRECTORY / language
        execute = executor(workflow, retained, root, selected)
        found = native_context.target_inventory(profile, retained, selected.get('cpp-demangler'), execute)
        covered.update((language, name) for name in profile['local_inputs'])
        for item in found:
            function = item['function']
            name = function['source_file']
            if not workflow.project_policy.selected(name, args.configuration['sources']):
                continue
            discovered = {**item['models'], 'globals': item['globals'], 'functions': [function], 'entrypoints': []}
            entry = workflow.inventory_entry(function, discovered, name, language,
                profile['local_inputs'][name], snapshot, args)
            entry.update(target=item['target'], unit=item['unit'], native_context={'language': language})
            entry['id'] = workflow.identity({'entry': entry['id'], 'target': item['target'], 'unit': item['unit'],
                                             'inputs': profile['local_inputs']})[:20]
            if entry['status'] == 'ready':
                try:
                    native_workers.validate(profile, entry, harness.corpus(entry, args.cases)[0])
                    if native_source.enabled(entry):
                        native_source.configuration(entry, 'http://127.0.0.1:4318', 'oteleq-native-planning')
                except ValueError as error:
                    entry.update(status='blocked', reason=str(error))
            workflow.filesystem_effects.bind(entry, args.configuration)
            entries.append(entry)
    return tools, artefacts, entries, covered


def verify(workflow, workspace: Path, data: dict) -> None:
    """Verify retained context and recheck searches against the current source root."""
    profiles = data.get('native_projects', {})
    if not profiles:
        return
    native_project.require(context_manifest(workflow, workspace) == data['native_context_manifest'],
                           'retained native context changed')
    for language, profile in profiles.items():
        selected = {name: Path(path) for name, path in profile['tools'].items()}
        retained = workspace / DIRECTORY / language
        check = workspace / 'runs' / ('native-input-check-' + uuid.uuid4().hex) / language
        native_workspace.verify_copy(profile, retained, Path(data['source']), check,
                                     executor(workflow, check.parent, Path(data['otelc_root']), selected))


def preview(workflow, workspace: Path, entry: dict, case: dict, destination: Path, data: dict) -> None:
    """Review helpers reference the one immutable snapshot instead of copying it per case."""
    profile = data['native_projects'][entry['language']]
    project = workspace / 'snapshot'
    recipe = native_workers.materialise(project, profile, entry, case['arguments'], destination / 'helpers',
                                         **({'unprofiled': True} if native_source.enabled(entry) else {}))
    workflow.write(destination / 'recipe.json', recipe)


def driver_inputs(profile: dict, retained: Path, step: dict, folder: Path, execute) -> dict:
    """Bind headers read by the neutral driver as well as application unit inputs."""
    arguments = step['command']
    position = arguments.index('-c')
    source = Path(arguments[position + 1])
    unit = {'source': source.name, 'directory': '.', 'compiler': arguments[0], 'flags': arguments[1:position]}
    document = native_frontend.inspect(unit, source.parent, profile['frontend'], retained / 'frontend',
                                       folder / 'driver-inputs', execute, mode='inputs')
    return native_frontend.input_state(document, unit, source.parent)


def build(workflow, workspace: Path, data: dict, entry: dict, case: dict, project: Path,
          prefix: list, environment: dict, folder: Path, lane: str) -> list:
    """Compile actual unit recipes and retain every command, object and final binary."""
    native_project.require(lane in ('baseline', 'instrumented_on'), 'unsupported execution lane')
    profile = data['native_projects'][entry['language']]
    directories(project, {entry['language']: profile})
    retained = workspace / DIRECTORY / entry['language']
    native_workspace.verify_copy(profile, retained, project, folder / 'input-check',
        executor(workflow, folder / 'discovery', Path(data['otelc_root']),
                 {name: Path(path) for name, path in profile['tools'].items()}))
    recipe = native_workers.materialise(project, profile, entry, case['arguments'], folder / 'helpers')
    workflow.write(folder / 'native-build.json', recipe)
    identities = {'helpers': recipe['assets'], 'outputs': {}}
    for index, step in enumerate(recipe['steps']):
        if step['kind'] == 'driver':
            identities['driver_inputs'] = driver_inputs(profile, retained, step, folder,
                executor(workflow, folder / 'discovery', Path(data['otelc_root']),
                         {name: Path(path) for name, path in profile['tools'].items()}))
        command = (native_workers.instrumented_command(step, list(map(str, prefix)), entry['language'])
                   if lane == 'instrumented_on' else step['command'])
        evidence = folder / ('build-' + str(index) + '-' + step['kind'])
        evidence.mkdir()
        workflow.write(evidence / 'command.json', list(map(str, command)))
        workflow.write(evidence / 'working-directory.json', step['directory'])
        result = workflow.execute(command, step['directory'], environment, evidence, timeout=120)
        native_project.require(result.returncode == 0, 'target build failed; inspect ' + str(evidence))
        identities['outputs'][step['output']] = workflow.capture.file_digest(Path(step['output']))
    native_project.require({name: workflow.capture.file_digest(Path(name)) for name in recipe['assets']} == recipe['assets'],
                           'generated native helper changed during the build')
    identities['build_assets'] = workflow.manifest(folder / 'helpers', max_file_bytes=workflow.MAX_TREE)
    workflow.write(folder / workflow.BUILD_IDENTITIES, identities)
    return [recipe['binary']] if lane == 'baseline' else [*prefix, 'run', recipe['binary']]


def verify_build(workflow, folder: Path) -> None:
    """Application execution cannot alter retained objects, SDK markers or helpers."""
    identities = workflow.read(folder / workflow.BUILD_IDENTITIES)
    native_project.require(workflow.manifest(folder / 'helpers', max_file_bytes=workflow.MAX_TREE) == identities['build_assets'],
                           'native build assets changed during application execution')
    for name, record in identities['driver_inputs']['dependencies'].items():
        path = Path(name)
        native_project.require(path.is_file() and str(path.resolve()) == record['resolved'] and
                               workflow.capture.file_digest(path) == record['sha256'],
                               'neutral native driver input changed: ' + name)
