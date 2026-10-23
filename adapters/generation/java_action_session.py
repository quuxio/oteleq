"""Host-owned Java invocation control, bound before releasing each typed call.

The last ordinary harness action is a drain barrier outside any envelope.
Application observations, final SDK health and decoded receipts remain separate.
"""

import copy
from pathlib import Path

import java_action
import java_action_receipt as receipt
import java_witness as witness


class Session:
    """Advance one serial JVM without putting control on application channels."""

    def __init__(self, harness: java_action.Harness, runtime: Path | None,
                 expected: dict, *, plain: bool, profile: str = witness.HANDLE_PROFILE):
        fields = witness.hash_fields(profile)
        witness.require(type(plain) is bool and len(harness.actions) >= 2,
                        "session needs calls and a final harness barrier")
        witness.require(type(expected) is dict and
                        (not expected if plain else set(expected) == set(fields)
                         and all(witness.hex_id(expected[key], 64) for key in fields)),
                        "missing independently expected action inputs")
        witness.require(plain or isinstance(runtime, Path),
                        "instrumented session needs its owned runtime")
        self.harness, self.runtime, self.plain, self.profile = harness, runtime, plain, profile
        self.expected = expected.copy()
        self.case_id, self.attempt_id, self.actions = harness.case_id, harness.attempt_id, tuple(harness.actions)
        self.identity, self.pending, self.terminal = None, None, None
        self.armed, self.completed, self.controls = [], [], []

    def environment(self) -> dict[str, str]:
        """Use the same ordinary JDK rendezvous in baseline and instrumented lanes."""
        return self.harness.environment()

    def query(self, operation: str, *arguments: str, deadline: float) -> dict:
        """Retain every actual reply before interpreting it."""
        value = witness.request(self.runtime / 'witness.sock', operation, *arguments,
                                deadline=deadline, profile=self.profile)
        self.controls.append({'operation': operation, 'arguments': list(arguments), 'reply': copy.deepcopy(value)})
        return value

    def _end(self, deadline: float) -> bool:
        """Finish the previous scope before inspecting another harness action."""
        if self.pending is None:
            return True
        value = self.query('end', self.identity.runtime_id, self.pending['scope_id'], deadline=deadline)
        self.identity.check(value)
        if value['error'] in ('root_active', 'incomplete'):
            return False
        scope = witness.context(value, self.identity, thread_id=self.pending['thread_id'],
                                cookie=self.pending['cookie'], sequence=self.pending['sequence'],
                                case_id=self.case_id, attempt_id=self.attempt_id,
                                scope_id=self.pending['scope_id'])
        witness.require(scope['producer_complete'], "end did not complete the intended action")
        self.completed.append(copy.deepcopy(value))
        self.pending = None
        return True

    def _arm(self, ready: dict, process, deadline: float) -> dict:
        """Bind actual harness thread and frozen caller inputs before release."""
        value = self.query('status', deadline=deadline)
        if self.identity is None:
            self.identity = witness.Identity.bind(value, self.expected, pid=process.pid, profile=self.profile)
        scope = value['scope']
        witness.require(scope is not None, "ready harness has no producer context")
        current = witness.context(value, self.identity, thread_id=ready['thread_id'],
                                  cookie=scope['cookie'], sequence=scope['sequence'])
        witness.require(current['phase'] == 'ready'
                        and all(current[key] is None for key in ('scope_id', 'case_id', 'attempt_id')),
                        "producer context was already armed or is not ready")
        if witness.profile_version(self.profile) == 3:
            witness.require(current['route_verified'] is False, "handle route verified before the call")
        seen = {(item['scope']['cookie'], item['scope']['sequence']) for item in self.armed}
        witness.require((current['cookie'], current['sequence']) not in seen, "producer reused an action context")
        args = (self.identity.runtime_id, current['cookie'], current['sequence'], self.case_id, self.attempt_id,
                self.expected['build_sha256'], self.expected['selection_sha256'], self.expected['tooling_sha256'],
                self.expected['wrapper_probe_id'], self.expected['policy_sha256'], ready['thread_id'])
        if witness.profile_version(self.profile) == 3:
            args += (self.expected['route_binding_sha256'],)
        armed = self.query('arm', *args, deadline=deadline)
        scope = witness.context(armed, self.identity, thread_id=ready['thread_id'], cookie=current['cookie'],
                                sequence=current['sequence'], case_id=self.case_id, attempt_id=self.attempt_id)
        witness.require(scope['phase'] == 'armed' and scope['scope_id'] is not None,
                        "producer did not arm the intended action")
        if witness.profile_version(self.profile) == 3:
            witness.require(scope['route_verified'] is False, "handle route verified before release")
        witness.require(scope['scope_id'] not in {item['scope']['scope_id'] for item in self.armed},
                        "producer reused an action scope")
        return copy.deepcopy(scope)

    def poll(self, process, deadline: float) -> None:
        """Make one bounded control step under the executor's original deadline."""
        witness.require((self.harness.case_id, self.harness.attempt_id, tuple(self.harness.actions))
                        == (self.case_id, self.attempt_id, self.actions), "private action plan changed")
        if not self.plain and not self._end(deadline):
            return
        ready = self.harness.poll(process, deadline)
        if ready is None:
            return
        witness.require(ready['case_id'] == self.case_id and ready['attempt_id'] == self.attempt_id
                        and ready['pid'] == process.pid
                        and ready['action_id'] == self.actions[self.harness.position],
                        "harness readiness differs from the frozen action")
        if self.harness.position == len(self.actions) - 1:
            witness.require(self.plain or len(self.completed) == len(self.actions) - 1,
                            "final barrier preceded action completion")
            self.terminal = ready.copy()
        elif not self.plain:
            scope = self._arm(ready, process, deadline)
            self.armed.append({'ready': ready.copy(), 'scope': scope})
            self.pending = scope
        self.harness.release(deadline)

    def finish(self, process) -> None:
        """An exited JVM cannot replace an unfinished action or drain barrier."""
        self.harness.finish(process)
        witness.require(self.terminal is not None and self.pending is None,
                        "JVM ended before its final action barrier")
        witness.require(self.plain or len(self.completed) == len(self.armed) == len(self.actions) - 1,
                        "missing completed invocation scopes")

    def receipt_actions(self, failed: list[bool]) -> list[receipt.Action]:
        """Join pre-release identities to separately captured application outcomes."""
        witness.require(not self.plain and self.terminal is not None and self.pending is None
                        and type(failed) is list and len(failed) == len(self.actions) - 1
                        and all(type(value) is bool for value in failed)
                        and len(self.armed) == len(self.completed) == len(failed),
                        "application outcomes do not cover the completed action plan")
        return [receipt.Action(self.actions[index], self.case_id, self.attempt_id,
                               item['ready']['thread_id'], item['scope']['cookie'], item['scope']['sequence'],
                               item['scope']['scope_id'], outcome)
                for index, (item, outcome) in enumerate(zip(self.armed, failed))]
