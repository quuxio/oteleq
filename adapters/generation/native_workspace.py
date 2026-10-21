"""Recheck native inputs at each fresh private root without rewriting old evidence."""
from pathlib import Path

import native_frontend
import native_project


def relocated(value: str | None, original: Path, project: Path) -> str | None:
    """Only application-root paths move; SDK and system inputs retain their roots."""
    if value is None:
        return None
    path = Path(value)
    return str(project / path.relative_to(original)) if path.is_relative_to(original) else value


def expected_inputs(prepared: dict, unit: dict, project: Path) -> dict:
    """Derive a fresh launch binding while keeping discovery provenance intact."""
    original = Path(prepared['source_root'])
    dependencies = {}
    for name, record in unit['dependencies'].items():
        logical = relocated(name, original, project)
        dependencies[logical] = {**record, 'resolved': relocated(record['resolved'], original, project)}
    probes = [{**item, **{name: relocated(item[name], original, project) for name in ('source', 'target')}}
              for item in unit['probes']]
    return {'dependencies': dependencies, 'probes': probes}


def verify_copy(prepared: dict, retained: Path, project: Path, checks: Path, execute) -> None:
    """Refuse altered source, tools, dependencies and positive/negative searches."""
    project, checks = project.resolve(), checks.resolve()
    native_project.require(not checks.is_relative_to(project), 'input checks must be outside application source')
    compiler = prepared['compiler']
    native_project.require(Path(compiler['path']).is_file() and
                           native_project.digest(Path(compiler['path'])) == compiler['sha256'],
                           'selected compiler changed')
    for name, expected in prepared['local_inputs'].items():
        path = project / name
        native_project.require(path.is_file() and path.resolve() == path and not path.is_symlink() and
                               native_project.digest(path) == expected, 'private project input changed: ' + name)
    checks.mkdir(parents=True, exist_ok=False)
    for key, unit in prepared['units'].items():
        metadata = retained / 'units' / key / 'metadata.json'
        native_project.require(metadata.is_file() and not metadata.is_symlink() and
                               native_project.digest(metadata) == unit['metadata_sha256'],
                               'retained compiler metadata changed: ' + key)
        data = native_frontend.inspect(unit, project, prepared['frontend'], retained / 'frontend',
                                       checks / key, execute, mode='inputs')
        actual = native_frontend.input_state(data, unit, project)
        native_project.require(actual == expected_inputs(prepared, unit, project),
                               'private compiler inputs or preprocessor search results changed: ' + unit['source'])
