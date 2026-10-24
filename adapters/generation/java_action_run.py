"""Compose generated Java actions with metric controls and retain host evidence."""

from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import tomllib
import uuid

import java_action
import java_action_launch
import java_action_session
import java_actions
import java_graph
import java_launch
import java_witness as witness
import otelc_capture as capture
import typed_capture

DIRECTORY = 'java-actions'
RECORD = 'record.json'
MAX_RECORD = witness.MAX_FINAL
MAX_CONTROL_FILES = 16


def control_chunks(rows: list[dict]) -> list[bytes]:
    """Retain the bounded reply history in independently bounded JSON arrays."""
    chunks, current, size = [], [], 2
    for row in rows:
        raw = json.dumps(row, separators=(',', ':'), allow_nan=False).encode()
        witness.require(len(raw) + 2 <= MAX_RECORD, 'action control record exceeds its file budget')
        if size + len(raw) + bool(current) > MAX_RECORD:
            chunks.append(b'[' + b','.join(current) + b']')
            current, size = [], 2
        size += len(raw) + bool(current)
        current.append(raw)
    if current:
        chunks.append(b'[' + b','.join(current) + b']')
    witness.require(len(chunks) <= MAX_CONTROL_FILES, 'action control history exceeds its file budget')
    return chunks


def outcomes(raw: bytes, entry: dict, case: dict) -> list[bool]:
    """Use the ordinary typed parser, independently of all producer replies."""
    witness.require(('sequence_configuration' in entry) == ('sequence' in case),
                    'frozen case and typed observer disagree about ordered actions')
    if 'receiver_fixture' in entry:
        boundary = java_graph.boundaries(raw, entry)
        rows = boundary['steps'] if 'sequence' in case else [boundary]
    else:
        witness.require('sequence' not in case, 'static action sequence needs its own typed observer')
        _, outcome, _ = typed_capture.scalar_capture(raw, entry)
        rows = [{'outcome': outcome}]
    witness.require(len(rows) == len(java_actions.action_ids(case)) - 1,
                    'typed outcomes differ from the frozen action count')
    return [row['outcome']['kind'] == 'error' for row in rows]


class Session:
    """Keep both host controllers under one executor deadline and JVM identity."""

    def __init__(self, folder: Path, runtime: Path, entry: dict, case: dict, *, plain: bool, metrics=None):
        witness.require(java_actions.enabled(entry) and isinstance(runtime, Path),
                        'generated actions need their explicit owned prepared runtime')
        compiled = java_action_launch.seals(folder)
        expected = {}
        if not plain:
            application = capture.strict_json((folder / java_launch.APPLICATION_FILE).read_bytes())
            launch = capture.strict_json((folder / java_launch.LAUNCH_FILE).read_bytes())
            data = tomllib.loads((folder / 'policy.toml').read_text())
            owner, _ = java_launch.target(entry, application, folder / 'project')
            expected = java_action_launch.verify(launch, folder=folder, runtime=runtime, entry=entry,
                application=application, classes=folder / java_launch.CLASSES, data=data, owner=owner)
        witness.require(java_action_launch.seals(folder) == compiled,
                        'compiled action inputs changed before execution')
        self.compiler_seals = compiled
        self.folder, self.metrics = folder, metrics
        self.record_snapshots = {}
        harness = java_action.Harness(runtime.parent / 'h', java_actions.case_id(case),
                                      uuid.uuid4().hex + uuid.uuid4().hex, java_actions.action_ids(case))
        try:
            self.action = java_action_session.Session(harness, runtime, expected, plain=plain,
                                                      profile=entry[java_actions.FIELD])
        except BaseException:
            harness.close()
            raise

    def environment(self) -> dict:
        return self.action.environment()

    def poll(self, process, deadline: float) -> None:
        if self.metrics is not None:
            self.metrics.poll(process, deadline)
        self.action.poll(process, deadline)

    def finish(self, process) -> None:
        self.action.finish(process)
        if self.metrics is not None:
            self.metrics.finish(process)

    def close(self) -> None:
        """Retain partial records as well as completed executions; always close sockets."""
        self.action.harness.close()
        root = self.folder / DIRECTORY
        root.mkdir(mode=0o700)
        controls = []
        for index, raw in enumerate(control_chunks(self.action.controls)):
            name = 'controls-' + str(index) + '.json'
            self.publish(root, name, raw)
            controls.append({'file': name, 'sha256': capture.digest(raw)})
        value = {'schema_version': 1, 'profile': self.action.profile, 'plain': self.action.plain,
                 'case_id': self.action.case_id, 'attempt_id': self.action.attempt_id,
                 'actions': list(self.action.actions), 'expected': self.action.expected,
                 'compiler_inputs': {'bindings_sha256': capture.digest(self.compiler_seals[0].raw),
                                    'record_sha256': capture.digest(self.compiler_seals[1].raw)},
                 'identity': asdict(self.action.identity) if self.action.identity is not None else None,
                 'harness': self.action.harness.records, 'armed': self.action.armed,
                 'completed': self.action.completed, 'terminal': self.action.terminal,
                 'controls': controls}
        raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
        self.publish(root, RECORD, raw)

    def publish(self, root: Path, name: str, raw: bytes) -> None:
        """Publish one fixed private file and retain its coherent opened snapshot."""
        witness.require(len(raw) <= MAX_RECORD, 'generated action record exceeds its byte budget')
        descriptor = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        self.record_snapshots[name] = witness.private_snapshot(root, name, MAX_RECORD)

    def audit(self) -> str:
        """Published host records must still be the same opened-file snapshot."""
        root = self.folder / DIRECTORY
        witness.require(java_action_launch.seals(self.folder) == self.compiler_seals,
                        'compiled action inputs changed during execution')
        witness.require(RECORD in self.record_snapshots and {path.name for path in root.iterdir()} == set(self.record_snapshots)
                        and all(witness.private_snapshot(root, name, MAX_RECORD) == snapshot
                                for name, snapshot in self.record_snapshots.items()),
                        'retained generated action record changed or is unavailable')
        return capture.digest(self.record_snapshots[RECORD].raw)


@contextmanager
def retained(options: dict):
    """Preserve a primary execution failure if its separate retention audit fails."""
    session = options.get('interaction')
    if not isinstance(session, Session):
        yield
        return
    try:
        yield
    except BaseException as error:
        try:
            session.close()
        except Exception as audit:
            error.add_note('Java action evidence retention also failed: ' + str(audit))
        raise
    else:
        session.close()
