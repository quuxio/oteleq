"""Drive native metric states around ordered calls in one owned application."""

from pathlib import Path
import time

import live_control
import native_control
import native_execution
import native_inputs
import native_rendezvous
import native_sequence
from native_protocol import digest, encoded, require, same
from otelc_capture import strict_json

INTERVAL_MS = 1000
MAX_STATUSES = 4096
MAX_RECORD_BYTES = 8 * 1024 * 1024


class Session:
    """Compose with the pre-exec owner and preserve its deadline and process pair."""

    def __init__(self, launch, folder: Path, entry: dict, sequence: list[dict],
                 arguments: list, bodies: list, maximum: int):
        self.sequence_json = encoded(native_sequence.concrete(entry, sequence, arguments))
        self.entry_json = encoded(entry)
        self.launch, self.folder, self.bodies = launch, folder, bodies
        require(type(bodies) is list and type(maximum) is int and maximum > 0
                and launch.intent.lifetime_kind() is None,
                'native controls require a bounded function-only capture')
        self.maximum = maximum
        self.checkpoints = native_rendezvous.Rendezvous(folder / 'native-rendezvous', len(sequence))
        self.started = self.client = self.holding = self.observation = self.final = None
        self.statuses = 0
        self.publications: list[native_inputs.Record] = []
        self.record = {'schema_version': 1, 'kind': 'oteleq.native.live-controls',
            'plain': launch.intent.plain, 'pid': None, 'supervisor_pid': None,
            'policy_sha256': digest(launch.intent.policy()),
            'selection_sha256': digest(launch.intent.selection()),
            'interval_ms': INTERVAL_MS, 'steps': [], 'restored': None}

    def sequence(self) -> list[dict]:
        """Return fresh data, never a mutable alias to the frozen case request."""
        return strict_json(self.sequence_json)

    def environment(self) -> dict:
        """Only the neutral driver consumes these private checkpoint bindings."""
        return self.checkpoints.environment()

    def verify(self) -> None:
        """Previously accepted frames and host publications keep their original facts."""
        self.checkpoints.verify()
        if self.client is not None:
            self.client.verify()
        for record in self.publications:
            record.verify()
        for held in (self.observation, self.final):
            if held is not None:
                held.verify()

    def publish(self) -> None:
        """Retain successive immutable snapshots, without the SDK endpoint token."""
        import native_session

        require(len(encoded(self.record).encode()) <= MAX_RECORD_BYTES,
                'native control transcript exceeds its byte budget')
        path = self.folder / ('native-live-' + str(len(self.publications)) + '.json')
        self.publications.append(native_session.publish(path, self.record))

    def bind(self, started: native_execution.Started) -> None:
        """The existing owner must have verified the actual kernel process pair first."""
        require(type(started) is native_execution.Started and started.launch is self.launch,
                'native controls have another owned preparation')
        if self.started is None:
            started.verify()
            self.started = started
            self.record.update(pid=started.owner.application_pid, supervisor_pid=started.owner.pid)
            if not self.launch.intent.plain:
                self.client = native_control.connect(self.launch.intent.runtime / 'app' / live_control.CONTROL_FILE,
                                                     started.owner.application_pid)
        require(self.started is started, 'native controls changed application owner')

    def query(self, command: str, deadline: float) -> dict | None:
        """Keep response accounting and policy joins separate from transport parsing."""
        if self.launch.intent.plain:
            return None
        self.statuses += 1
        require(self.statuses <= MAX_STATUSES, 'native control response budget exceeded')
        value = self.client.request(command, deadline)
        if command == 'health':
            native_control.running_health(value, pid=self.record['pid'],
                language=self.launch.intent.context().language, policy=self.record['policy_sha256'],
                selection=self.record['selection_sha256'])
        return value

    def transition(self, requested: dict, deadline: float) -> list[dict]:
        """Bound independent setters and the effective export-off barrier."""
        if self.launch.intent.plain:
            return []
        result = self.client.switch(requested, deadline)
        self.statuses += len(result)
        require(self.statuses <= MAX_STATUSES, 'native control response budget exceeded')
        return result

    def before(self, index: int, deadline: float) -> None:
        """Verify the initial policy and that no selected call ran between checkpoints."""
        requested = self.sequence()[index]['metrics']
        history = self.transition(requested, deadline)
        if history:
            require(index != 0 or all(history[0]['status'][key] is flag for key, flag in requested.items()),
                    'native startup state differs from its frozen first call')
        flushed, health = self.query('flush', deadline), self.query('health', deadline)
        if health is not None:
            previous = self.record['steps'][-1]['after']['settled']['function_accounting']['ended'] if index else '0'
            require(health['function_accounting']['ended'] == previous
                    and all(health['controls'][key] is flag for key, flag in requested.items()),
                    'native selected work or controls changed outside a declared call')
        self.record['steps'].append({'id': self.sequence()[index]['id'], 'requested': requested,
            'before': {'history': history, 'flush': flushed, 'health': health, 'cursor': len(self.bodies)},
            'after': None})
        self.publish()
        self.checkpoints.acknowledge()

    def after(self, index: int, deadline: float) -> None:
        """The closed original frame must exist before its call can be acknowledged."""
        self.checkpoints.frame(index)
        require(sum(frame.size for frame in self.checkpoints.frames) * 2 < min(self.maximum, native_sequence.MAX_BYTES),
                'native frames exceed the case capture budget')
        status, flushed, health = (self.query(command, deadline) for command in ('status', 'flush', 'health'))
        step = self.record['steps'][index]
        if health is not None:
            previous = step['before']['health']['function_accounting']['ended']
            require(int(health['function_accounting']['ended']) > int(previous)
                    and all(health['controls'][key] is flag for key, flag in step['requested'].items()),
                    'native declared call did not complete under its requested controls')
        self.holding = {'index': index, 'status': status, 'flush': flushed, 'health': health,
            'started_ns': time.monotonic_ns(),
            'until': time.monotonic() + (0 if all(step['requested'].values()) else INTERVAL_MS / 1000)}

    def settle(self, deadline: float) -> None:
        """An off-state window includes at least one complete export interval."""
        pending = self.holding
        step = self.record['steps'][pending['index']]
        flushed, health = self.query('flush', deadline), self.query('health', deadline)
        end = len(self.bodies)
        metric_indices = [index for index in range(step['before']['cursor'], end)
                          if self.bodies[index][0] == '/v1/metrics']
        require(all(step['requested'].values()) or not metric_indices,
                'native disabled metrics reached the receiver')
        if health is not None:
            require(health['function_accounting'] == pending['health']['function_accounting']
                    and all(health['controls'][key] is flag for key, flag in step['requested'].items())
                    and (all(step['requested'].values()) or health['controls']['effective_emission_off']),
                    'native work or metric controls changed while the call was paused')
        step['after'] = {key: pending[key] for key in ('status', 'flush', 'health')}
        step['after'].update(settled_flush=flushed, settled=health, cursor=end,
                             metric_bodies=metric_indices, held_ns=time.monotonic_ns() - pending['started_ns'])
        self.holding = None
        self.publish()
        self.checkpoints.acknowledge()

    def restore(self, deadline: float) -> None:
        """Restore and flush both flags before the same application can terminate."""
        history = self.transition({'collection': True, 'emission': True}, deadline)
        flushed, health = self.query('flush', deadline), self.query('health', deadline)
        if health is not None:
            require(health['function_accounting'] == self.record['steps'][-1]['after']['settled']['function_accounting']
                    and all(health['controls'][key] is True for key in ('collection', 'emission')),
                    'native restoration changed selected work or failed to restore flags')
        self.record['restored'] = {'history': history, 'flush': flushed, 'health': health, 'cursor': len(self.bodies)}
        self.publish()
        self.checkpoints.acknowledge()

    def poll(self, started: native_execution.Started, deadline: float) -> None:
        """Advance only a ready neutral-driver boundary under the original deadline."""
        require(time.monotonic() < deadline, 'native live schedule deadline expired')
        self.verify()
        if self.checkpoints.position == len(self.checkpoints.phases):
            return
        if self.checkpoints.ready() is None:
            return
        self.bind(started)
        if self.holding is not None:
            if time.monotonic() >= self.holding['until']:
                self.settle(deadline)
            return
        phase = self.checkpoints.phases[self.checkpoints.position]
        if phase == 'finish':
            self.restore(deadline)
        elif phase.startswith('before-'):
            self.before(self.checkpoints.position // 2, deadline)
        else:
            self.after(self.checkpoints.position // 2, deadline)

    def finish(self, completed: native_execution.Execution) -> None:
        """A successful exit cannot replace any missing frame, boundary or restoration."""
        require(type(completed) is native_execution.Execution and completed.started is self.started and self.holding is None
                and self.record['restored'] is not None, 'native live schedule did not finish')
        self.checkpoints.finish()
        raw = native_sequence.container(tuple(self.checkpoints.frames), tuple(self.sequence()))
        native_sequence.decode(raw, strict_json(self.entry_json))
        self.observation = native_sequence.publish(self.folder / 'observation', raw, self.maximum)
        import native_session

        self.final = native_session.publish(self.folder / 'native-controls.json', self.record)
        self.verify()
