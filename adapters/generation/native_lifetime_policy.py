"""Public native lifetime selection and independent per-test expectations."""

from pathlib import PurePosixPath

import native_lifetime_intent as caller
import native_lifetime_build as builds
import native_lifetime_inventory as inventory
import native_telemetry
from native_protocol import encoded, fields, require, same
import otelc_capture as capture

OBJECT = 'native-objects-owned-v1'
RESOURCE = 'native-resources-owned-v1'
PROFILES = {OBJECT: ('object', 'cpp', 4), RESOURCE: ('resource', 'c', 5)}
EXPECTATIONS = 'lifetime_expectations'
SOURCES = 'native_lifetime_sources'
MAX_OBSERVATIONS = 4096


def patterns(value: object) -> list[str]:
    """Keep common source/type glob strings bounded and free from NUL bytes."""
    require(type(value) is list and len(value) <= 1024 and all(
        type(row) is str and 0 < len(row) <= 4096 and '\0' not in row for row in value),
        'invalid native lifetime selection patterns')
    return value.copy()


def options(value: object) -> dict:
    """Explicit type selection is independent of the instances expected by a test."""
    require(type(value) is dict and set(value) <= {'include', 'exclude', 'max_live'}
            and 'include' in value, 'native lifetime profile requires explicit type include patterns')
    included, excluded = patterns(value['include']), patterns(value.get('exclude', []))
    maximum = value.get('max_live', 4096)
    require(bool(included) and type(maximum) is int and 1 <= maximum <= 1_000_000,
            'invalid native lifetime type selection or instance capacity')
    return {'include': included, 'exclude': excluded, 'max_live': maximum}


def kind(entry: dict) -> str | None:
    """Language alone never selects a lifetime instrumentation profile."""
    profile = entry.get('native_options', {}).get('profile')
    if entry.get('native_backend') != 'prepared' or profile not in PROFILES:
        return None
    selected, language, _ = PROFILES[profile]
    require(entry.get('language') == language, 'native lifetime profile has another language')
    return selected


def path(value: object) -> list[int]:
    """One generated scalar call is root zero; nested serial paths stay explicit."""
    require(type(value) is list and 1 <= len(value) <= 64 and value[0] == 0
            and all(type(index) is int and 0 <= index < native_telemetry.MAX_SPANS for index in value),
            'invalid native lifetime call path')
    return value.copy()


def expectations(value: object, language: str) -> list[dict]:
    """Counts, completion and exception outcomes come from the frozen test contract."""
    require(type(language) is str and language in ('c', 'cpp') and type(value) is list
            and len(value) <= MAX_OBSERVATIONS, 'invalid native lifetime fixture language or observation budget')
    result = []
    for row in value:
        require(type(row) is dict and {'type', 'creation_path', 'complete'} <= set(row)
                and set(row) <= {'type', 'creation_path', 'release_path', 'complete', 'exception_exit'},
                'invalid native lifetime fixture observation fields')
        name, complete = row['type'], row['complete']
        require(type(name) is str and 0 < len(name) <= 4096 and name.strip() and '\0' not in name
                and type(complete) is bool, 'invalid expected native lifetime type or completion')
        creation = path(row['creation_path'])
        release = path(row.get('release_path')) if complete else row.get('release_path')
        exception = row.get('exception_exit')
        require((complete or release is None) and
                (type(exception) is bool if language == 'cpp' and complete else exception is None),
                'native lifetime release or destructor exception expectation differs')
        result.append({'type': name, 'creation_path': creation, 'release_path': release,
                       'complete': complete, 'exception_exit': exception})
    require(len(encoded(result).encode()) <= 1024 * 1024, 'native lifetime expectations exceed their byte budget')
    return result


def bind(entry: dict, value: list[dict]) -> None:
    """A lifetime fixture cannot be silently ignored by another provider or profile."""
    require(kind(entry) is not None, 'lifetime expectations require an explicit native lifetime profile')
    entry[EXPECTATIONS] = expectations(value, entry['language'])


def require_expectations(entry: dict) -> None:
    """An explicit empty declaration means zero; absence remains a visible gap."""
    selected = kind(entry)
    if selected is None:
        require(EXPECTATIONS not in entry, 'native lifetime expectations have no selected profile')
    else:
        require(EXPECTATIONS in entry and same(entry[EXPECTATIONS], expectations(entry[EXPECTATIONS], entry['language'])),
                'native lifetime profile requires declared fixture observations, including an explicit empty list')


def source_selection(profile: dict, selection: dict, accepts) -> dict:
    """Materialise caller-known source names using the generation policy's glob rules."""
    require(type(profile) is dict and type(profile.get('local_inputs')) is dict
            and all(type(name) is str for name in profile['local_inputs']),
            'native lifetime source selection requires caller-owned project inputs')
    names = sorted(name for name in profile['local_inputs'] if accepts(name, selection))
    require(1 <= len(names) <= 1024 and all(type(name) is str and name
            and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
            and not any(char in name for char in '*?\0') for name in names),
            'native lifetime source selection needs bounded literal project input paths')
    return {'include': names, 'exclude': []}


def bind_sources(entry: dict, profile: dict, selection: dict, accepts) -> None:
    """Header/type selection is explicit and remains bound to the original compiler context."""
    if kind(entry) is not None:
        selected = source_selection(profile, selection, accepts)
        require(entry['path'] in selected['include'], 'native lifetime sources exclude the selected function')
        entry[SOURCES] = selected


def unique_target(entry: dict, found: list[dict], identity) -> None:
    """A demangled-name selector must not instrument a different source function."""
    if kind(entry) is None:
        return
    names = set(entry[SOURCES]['include'])
    matches = set()
    for item in found:
        function = item['function']
        source = function['source_file']
        if item['target'] == entry['target'] and source in names and identity({
                **function, 'path': source, 'language': entry['language']}) == entry['otelc_function']:
            matches.add((source, function['source_offset'], function['symbol']))
    require(matches == {(entry['path'], entry['source_offset'], entry['symbol'])},
            'native lifetime function selector is ambiguous across selected source inputs')


def apply(entry: dict, value: dict) -> None:
    """Extend the common policy only after the fixture and source bindings exist."""
    if kind(entry) is None:
        return
    require_expectations(entry)
    selected = fields(entry.get(SOURCES), {'include', 'exclude'}, 'native lifetime source selection')
    require(bool(patterns(selected['include'])) and not patterns(selected['exclude']),
            'native lifetime source selection must retain literal included inputs')
    life = options(entry['native_options']['lifetimes'])
    value['sources'] = {'include': selected['include'].copy(), 'exclude': []}
    value['lifetimes'] = {'enabled': True, **life, 'release_methods': ['close']}


def resolve(intent: builds.Intent, declarations: list[dict]) -> tuple[caller.Observation, ...]:
    """Resolve user type names from earlier caller compiler facts before SDK builds."""
    require(type(intent) is builds.Intent, 'native lifetime expectations require caller build intent')
    intent.verify()
    language = 'cpp' if intent.kind == 'object' else 'c'
    values = expectations(declarations, language)
    names = {}
    for _, raw in intent.semantics:
        selected = inventory.catalogue(capture.strict_json(raw), intent.kind, intent.base.policy(), intent.base.project)
        for row in selected['types']:
            names.setdefault(row['name'], set()).add(row['usr'])
    result = []
    for value in values:
        identities = names.get(value['type'], set())
        require(len(identities) == 1, 'expected native lifetime type is absent or ambiguous in caller compiler facts')
        result.append(caller.Observation(next(iter(identities)), value['type'], tuple(value['creation_path']),
            None if value['release_path'] is None else tuple(value['release_path']),
            value['complete'], value['exception_exit']))
    intent.verify()
    return tuple(result)
