"""Publish caller lifetime expectations before releasing an owned application."""

from dataclasses import dataclass
from pathlib import Path

import native_inputs as inputs
import native_lifetime_inventory as inventory
import native_prepared as prepared
from native_protocol import encoded, require, same
import native_session
import native_telemetry as telemetry
import otelc_capture as capture


@dataclass(frozen=True)
class Observation:
    """One ordered admission, its source type and declared serial call boundaries."""

    type_usr: str
    name: str
    creation_path: tuple[int, ...]
    release_path: tuple[int, ...] | None
    complete: bool
    exception_exit: bool | None = None

    def data(self) -> dict:
        """Use primitive closed values in retained expectation records."""
        return {'type_usr': self.type_usr, 'name': self.name,
                'creation_path': list(self.creation_path),
                'release_path': None if self.release_path is None else list(self.release_path),
                'complete': self.complete, 'exception_exit': self.exception_exit}


def validate(launch: prepared.Prepared, roots: tuple[str, ...], observations: tuple[Observation, ...]) -> dict:
    """Resolve expected names from independently frozen compiler facts, never OTLP."""
    require(type(launch) is prepared.Prepared and launch.intent.lifetime_kind() in ('object', 'resource'),
            'lifetime receipt requires its accepted prepared profile')
    require(type(roots) is tuple and 1 <= len(roots) <= 64
            and all(type(name) is str and 0 < len(name) <= 4096 and '\0' not in name for name in roots)
            and type(observations) is tuple and len(observations) < telemetry.MAX_SPANS,
            'invalid lifetime root or observation budget')
    intent = launch.intent.build.intent
    names, identities = {}, {}
    for _unit, raw in intent.semantics:
        selected = inventory.catalogue(capture.strict_json(raw), intent.kind,
                                       intent.base.policy(), intent.base.project)
        for row in selected['types']:
            require(row['usr'] not in identities or identities[row['usr']] == row['name'],
                    'inconsistent source lifetime type name')
            identities[row['usr']] = row['name']
            names.setdefault(row['name'], set()).add(row['usr'])
    for observation in observations:
        require(type(observation) is Observation and type(observation.type_usr) is str
                and type(observation.name) is str and 0 < len(observation.name) <= 4096
                and identities.get(observation.type_usr) == observation.name
                and len(names[observation.name]) == 1 and type(observation.complete) is bool,
                'unknown, ambiguous or invalid expected source lifetime')
        for path in (observation.creation_path, observation.release_path):
            require(path is None or type(path) is tuple and 1 <= len(path) <= 64
                    and all(type(index) is int and 0 <= index < telemetry.MAX_SPANS for index in path)
                    and path[0] < len(roots), 'invalid expected serial lifetime call path')
        require(observation.creation_path is not None
                and (observation.release_path is not None) == observation.complete
                and (type(observation.exception_exit) is bool if intent.kind == 'object'
                     and observation.complete else observation.exception_exit is None),
                'lifetime release, censoring or destructor boundary differs')
    return {'schema_version': 1, 'kind': 'oteleq.native.lifetime-intent',
            'native_profile': intent.kind,
            'preparation': {name: record.file.gate_identity() for name, record in
                            zip((prepared.REQUEST, prepared.PLAN, prepared.PREPARED), launch.records, strict=True)},
            'roots': list(roots), 'observations': [row.data() for row in observations],
            'scope': 'Declared synchronous serial selected call trees; no general action/thread attribution'}


@dataclass(frozen=True)
class Intent:
    """The original private record seals caller expectations before execution."""

    launch: prepared.Prepared
    roots: tuple[str, ...]
    observations: tuple[Observation, ...]
    record: inputs.Record

    def verify(self) -> None:
        """Retain accepted source, preparation and expectation file identities."""
        self.launch.verify()
        self.record.verify()
        require(same(self.record.value(), validate(self.launch, self.roots, self.observations)),
                'original lifetime caller expectations changed')


def freeze(launch: prepared.Prepared, path: Path, roots: tuple[str, ...],
           observations: tuple[Observation, ...]) -> Intent:
    """Publish new external expectations while the SDK runtime is still unused."""
    value = validate(launch, roots, observations)
    launch.verify()
    require({child.name for child in launch.intent.runtime.iterdir()} ==
            {prepared.REQUEST, prepared.PLAN, prepared.PREPARED},
            'lifetime expectations must precede owned execution')
    context = launch.intent.context()
    require(isinstance(path, Path) and path.is_absolute() and '..' not in path.parts
            and path.parent == path.parent.resolve(strict=True) and path.parent.is_dir()
            and not path.exists() and not path.is_symlink()
            and not any(capture.path_within(path, root) for root in
                        (context.project, context.output, context.sdk.root, context.sdk.directory,
                         launch.intent.runtime)) and len(encoded(value).encode()) <= inputs.MAX_RECORD,
            'lifetime expectations require a new bounded external file')
    result = Intent(launch, roots, observations, native_session.publish(path, value))
    result.verify()
    return result
