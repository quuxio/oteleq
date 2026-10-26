"""Validate native live replies against caller-owned process and policy identity."""

from dataclasses import dataclass
from pathlib import Path
import re
import time

import live_control
import native_health
import native_inputs
from native_protocol import fields, require, same

STATUS = {'schema_version', 'pid', 'collection', 'emission', 'effective_emission_off'}
COMMANDS = {'status', 'health', 'flush', 'collection on', 'collection off', 'emission on', 'emission off'}


def status(value: dict, pid: int) -> dict:
    """An effective-off claim cannot coexist with both metric flags enabled."""
    fields(value, STATUS, 'native control status')
    require(type(pid) is int and pid > 1
            and type(value['collection']) is type(value['emission']) is type(value['effective_emission_off']) is bool
            and same(value, {'schema_version': 1, 'pid': pid,
                'collection': value['collection'], 'emission': value['emission'],
                'effective_emission_off': value['effective_emission_off']})
            and not (value['effective_emission_off'] and value['collection'] and value['emission']),
            'native control status differs from its process, flags or effective barrier')
    return value


def running_health(value: dict, *, pid: int, language: str, policy: str, selection: str) -> dict:
    """Keep live pipeline unknowns explicit while checking paused function work."""
    fields(value, native_health.FIELDS, 'native running health')
    expected = {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': language,
        'scope': 'sdk_pipeline', 'pid': pid, 'phase': 'running', 'sdk_attached': True,
        'policy_sha256': policy, 'selection_sha256': selection, 'source_complete': False,
        'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable',
        'diagnostics': {'dropped': '0'}}
    require(language in ('c', 'cpp') and type(pid) is int and pid > 1
            and all(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest)
                    for digest in (policy, selection))
            and same({key: value[key] for key in expected}, expected),
            'native running health has another profile, process or policy')
    status(value['controls'], pid)
    fields(value['lifecycle'], {'flush', 'shutdown'}, 'native live lifecycle')
    require(value['lifecycle']['flush'] in ('not_started', 'succeeded')
            and value['lifecycle']['shutdown'] == 'not_started', 'native live lifecycle failed or ended')
    fields(value['metric_flush'], {'attempts', 'failed_attempts'}, 'native live flush')
    native_health.count(value['metric_flush']['attempts'])
    require(value['metric_flush']['failed_attempts'] == '0', 'native live flush failed')
    function = fields(value['function_accounting'], native_health.FUNCTIONS, 'native live functions')
    for key in native_health.FUNCTIONS - {'closed'}:
        native_health.count(function[key])
    require(function['closed'] is False and function['started'] == function['ended']
            and (function['registered'] != '0' or function['started'] == '0')
            and all(function[key] == '0' for key in ('active', 'lost', 'invalid', 'metadata_errors')),
            'native function work is active, lost or closed at a checkpoint')
    spans = fields(value['span_accounting'], native_health.SPANS, 'native live spans')
    for key in ('sampled_started', 'sampled_ended', 'sampled_active'):
        native_health.count(spans[key])
    require(same({key: spans[key] for key in ('processors_observed', 'batch_processors_observed',
                'queue_pending', 'queue_dropped', 'queue_evidence')},
                {'processors_observed': 1, 'batch_processors_observed': 1,
                 'queue_pending': None, 'queue_dropped': None, 'queue_evidence': 'unavailable'})
            and spans['sampled_started'] == spans['sampled_ended'] == function['ended']
            and spans['sampled_active'] == '0', 'native live trace accounting differs from paused calls')
    for name, unit in (('trace_exports', 'spans'), ('metric_exports', 'metric_points')):
        exports = fields(value[name], native_health.EXPORTS, 'native live exports')
        counts = {key: native_health.count(exports[key])
                  for key in native_health.EXPORTS - {'unit', 'exporters_observed'}}
        require(type(exports['exporters_observed']) is int and exports['exporters_observed'] == 1
                and exports['unit'] == unit
                and counts['batches_failed'] == counts['units_failed'] == 0
                and counts['batches_started'] == counts['batches_succeeded'] + counts['batches_pending']
                and counts['units_succeeded'] <= counts['units_started']
                and (counts['batches_pending'] > 0 or counts['units_started'] == counts['units_succeeded']),
                'native live exporter identity, losses or accounting differ')
    return value


@dataclass(frozen=True)
class Client:
    """The private endpoint must keep its original identity for the whole case."""

    path: Path
    pid: int
    identity: tuple
    descriptor: native_inputs.File | None = None

    def verify(self) -> None:
        if self.descriptor is not None:
            self.descriptor.verify()
        require(type(self.pid) is int and self.pid > 1
                and live_control.endpoint(self.path, self.pid)[1] == self.identity,
                'native control endpoint changed')

    def request(self, command: str, deadline: float) -> dict:
        """Only fixed commands can cross the authenticated bounded transport."""
        require(type(command) is str and command in COMMANDS, 'unsupported native live command')
        self.verify()
        value = live_control.exchange(self.path, command, self.pid, deadline,
                                      maximum=16384 if command == 'health' else 4096)
        self.verify()
        return value if command == 'health' else status(value, self.pid)

    def switch(self, requested: dict, deadline: float) -> list[dict]:
        """Set each flag independently and require the other flag to stay fixed."""
        require(type(requested) is dict and set(requested) == {'collection', 'emission'}
                and all(type(value) is bool for value in requested.values()), 'invalid native metric state')
        current = self.request('status', deadline)
        result = [{'command': 'status', 'status': current}]
        for name in ('collection', 'emission'):
            if current[name] is requested[name]:
                continue
            command = name + (' on' if requested[name] else ' off')
            changed = self.request(command, deadline)
            expected = {key: requested[name] if key == name else current[key]
                        for key in ('collection', 'emission')}
            require(all(changed[key] is value for key, value in expected.items()),
                    'native metric setter changed another flag or ignored its request')
            result.append({'command': command, 'status': changed})
            current = changed
        require(all(current[key] is value for key, value in requested.items()),
                'native metric transition did not reach the declared state')
        while not all(requested.values()) and not current['effective_emission_off']:
            require(len(result) < 128 and time.monotonic() < deadline,
                    'native metric export barrier did not settle within its budget')
            time.sleep(min(.02, max(0, deadline - time.monotonic())))
            current = self.request('status', deadline)
            require(all(current[key] is value for key, value in requested.items()),
                    'native metric flags changed while waiting for the export barrier')
            result.append({'command': 'status', 'status': current})
        return result


def connect(path: Path, pid: int) -> Client:
    """Bind only after the native owner has identified its actual SDK child."""
    require(type(pid) is int and pid > 1, 'native control requires an actual application PID')
    result = Client(path, pid, live_control.endpoint(path, pid)[1],
                    native_inputs.capture(path, maximum=live_control.MAX_DESCRIPTOR, private=True))
    result.verify()
    return result
