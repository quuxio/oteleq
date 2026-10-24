"""Independently bind generated action metadata to fixed prepared Java inputs."""

import json
import os
from pathlib import Path
import stat
from contextlib import contextmanager

import java_action_bindings as compiler
import java_actions as actions
import java_launch as launch
import java_provider as provider
import java_witness as witness

MAX_INPUT = 1024 * 1024


def bindings_file(folder: Path) -> Path:
    return folder / 'action-bindings/bindings.json'


def tooling(root: Path, folder: Path, runtime: Path) -> set[Path]:
    """Only these extra files may accompany the fixed instrumented recipe."""
    return {root / provider.HELPER, bindings_file(folder), runtime / 'witness.properties', runtime / 'witness.json'}


def snapshot(runtime: Path, name: str) -> witness.PrivateSnapshot:
    """Read bounded SDK inputs in their private directory without following links.

    Public preparation writes mode 0600 or 0644 input files under owned 0700.
    The separate final-report and binding readers still require mode 0600.
    """
    witness.require(name in ('witness.json', 'witness.properties', 'compiler-inputs.json')
                    and runtime == runtime.resolve(strict=True),
                    'invalid action launch input path')
    directory = runtime.lstat()
    witness.require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.getuid()
                    and stat.S_IMODE(directory.st_mode) == 0o700, 'unsafe action launch input directory')
    parent = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            witness.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                            and stat.S_IMODE(before.st_mode) in (0o600, 0o644)
                            and before.st_nlink == 1 and before.st_size <= MAX_INPUT,
                            'unsafe or oversized action launch input')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                raw = stream.read(MAX_INPUT + 1)
            states = (before, os.fstat(descriptor), os.stat(name, dir_fd=parent, follow_symlinks=False))
        finally:
            os.close(descriptor)
        directories = [directory, os.fstat(parent), runtime.lstat()]
        identities = [(item.st_dev, item.st_ino, item.st_mode, item.st_uid) for item in directories]
        witness.require(identities[0] == identities[1] == identities[2], 'action launch directory changed')
    finally:
        os.close(parent)
    signature = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
                              item.st_ctime_ns, item.st_mode, item.st_uid, item.st_nlink)
    identities = [signature(item) for item in states]
    witness.require(len(raw) == before.st_size <= MAX_INPUT and identities[0] == identities[1] == identities[2],
                    'action launch input changed while reading')
    return witness.PrivateSnapshot(raw, identities[0])


def seals(folder: Path) -> tuple:
    """Bind the compiler's published hash to the exact retained binding bytes."""
    path = bindings_file(folder)
    bound = witness.private_snapshot(path.parent, path.name, compiler.MAX_BINDINGS)
    record = snapshot(path.parent, 'compiler-inputs.json')
    value = provider.capture.strict_json(record.raw)
    witness.require(type(value) is dict and type(value.get('schema_version')) is int
                    and value['schema_version'] == 1 and value.get('profile') == witness.HANDLE_PROFILE
                    and value.get('bindings_sha256') == provider.capture.digest(bound.raw),
                    'compiled action binding publication differs')
    return bound, record


@contextmanager
def preserved_bindings(folder: Path):
    """Preparation cannot rewrite caller-owned compiler outputs, even on failure."""
    before = seals(folder)
    try:
        yield
    except BaseException as error:
        try:
            witness.require(seals(folder) == before, 'compiled action inputs changed during preparation')
        except (OSError, ValueError) as audit:
            error.add_note('Action binding input audit also failed: ' + str(audit))
        raise
    witness.require(seals(folder) == before, 'compiled action inputs changed during preparation')


def verify(value: dict, *, folder: Path, runtime: Path, entry: dict,
           application: dict, classes: Path, data: dict, owner: str) -> dict:
    """Recompute route, properties and every expected live header hash."""
    declared, route = actions.declarations(entry, owner, list(application['bindings']))
    path = bindings_file(folder)
    bound = witness.private_snapshot(path.parent, path.name, compiler.MAX_BINDINGS)
    document = provider.capture.strict_json(bound.raw)
    compiler.verify(document, declared, application, classes, profile=entry[actions.FIELD], route=route)
    properties = snapshot(runtime, 'witness.properties')
    metadata = snapshot(runtime, 'witness.json')
    expected_tail = [launch.identity(item) for item in (path, runtime / 'witness.properties', runtime / 'witness.json')]
    witness.require(value['tooling'][-3:] == expected_tail, 'action tooling tail differs')
    # The complete inventory was checked by java_launch.files. Re-read actual
    # identities in that recorded order before computing this protocol digest.
    inputs = [launch.identity(Path(item['path'])) for item in value['tooling'][:-2]]
    hashes = {'build_sha256': provider.digest(value['application']),
              'selection_sha256': value['selection_sha256'], 'policy_sha256': provider.digest(data),
              'tooling_sha256': provider.digest(inputs)}
    expected = {'schema_version': 3, 'kind': 'otelc.java-witness-launch', 'profile': entry[actions.FIELD],
                'socket': str(runtime / 'witness.sock'), 'final_report': str(runtime / 'witness-health.json'),
                **hashes, 'route': document['route'], 'bindings': document['bindings'],
                'bindings_sha256': provider.capture.digest(bound.raw),
                'runtime_confirmation_required': True, 'receiver_confirmation_required': True}
    actual = provider.capture.strict_json(metadata.raw)
    witness.require(json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True),
                    'SDK changed the independently expected action launch metadata')
    plan = {'schema_version': '3', 'profile': entry[actions.FIELD], 'socket': expected['socket'],
            **{name: hashes[name + '_sha256'] for name in ('build', 'selection', 'policy', 'tooling')}}
    origin = classes.resolve(strict=True).as_uri().replace('file:///', 'file:/', 1) + '/'
    for role, binding in document['bindings'].items():
        plan.update({role + '.' + key: item for key, item in binding.items()})
        plan[role + '.origin'] = origin
    plan.update({'route.' + key: str(item) for key, item in document['route'].items()})
    witness.require(properties.raw == launch.properties(plan).encode(), 'SDK changed the fixed action properties')
    witness.require(snapshot(runtime, 'witness.properties') == properties and snapshot(runtime, 'witness.json') == metadata
                    and witness.private_snapshot(path.parent, path.name, compiler.MAX_BINDINGS) == bound,
                    'action launch inputs changed after validation')
    return {**hashes, **{role + '_probe_id': document['bindings'][role]['probe_id'] for role in compiler.ROLES},
            'route_binding_sha256': document['route']['sha256']}
