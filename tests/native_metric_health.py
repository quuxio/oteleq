"""Independent fixed-corpus checks for native controls and paused SDK health."""

import re

import native_prepared_receipt as retained
from native_prepared_otlp import require, same


def count(value: object) -> int:
    require(type(value) is str and re.fullmatch(r'0|[1-9][0-9]{0,19}', value) is not None,
            'noncanonical native fixture counter')
    result = int(value)
    require(result < 2**64, 'native fixture counter overflow')
    return result


def status(value: dict, pid: int, flags: dict, *, settled: bool = True) -> None:
    require(type(flags) is dict and set(flags) == {'collection', 'emission'}
            and all(type(value) is bool for value in flags.values()), 'invalid native fixture flags')
    require(type(pid) is int and pid > 1 and type(value) is dict
            and type(value.get('effective_emission_off')) is bool, 'invalid native fixture status identity')
    effective = value['effective_emission_off']
    require(not effective if all(flags.values()) else effective or not settled,
            'native fixture effective metric state differs')
    same(value, {'schema_version': 1, 'pid': pid, **flags, 'effective_emission_off': effective})


def transition(rows: list, pid: int, previous: dict, requested: dict) -> None:
    """Only necessary independent setters may precede the effective-off barrier."""
    require(type(rows) is list and 1 <= len(rows) <= 128, 'missing native fixture transition')
    commands = ['status'] + [key + (' on' if requested[key] else ' off')
                             for key in ('collection', 'emission') if previous[key] is not requested[key]]
    require(len(rows) >= len(commands), 'missing independent native fixture setter')
    flags = dict(previous)
    for index, row in enumerate(rows):
        same(sorted(row), ['command', 'status'])
        command = commands[index] if index < len(commands) else 'status'
        same(row['command'], command)
        if command != 'status':
            key = command.split()[0]; flags[key] = requested[key]
        status(row['status'], pid, flags, settled=False)
    status(rows[-1]['status'], pid, requested)


def exports(value: dict, unit: str) -> None:
    names = {'batches_started', 'batches_succeeded', 'batches_failed', 'batches_pending',
             'units_started', 'units_succeeded', 'units_failed'}
    same(sorted(value), sorted(names | {'unit', 'exporters_observed'}))
    same(value['unit'], unit); same(value['exporters_observed'], 1)
    numbers = {key: count(value[key]) for key in names}
    require(numbers['batches_failed'] == numbers['units_failed'] == 0
            and numbers['batches_started'] == numbers['batches_succeeded'] + numbers['batches_pending']
            and numbers['units_succeeded'] <= numbers['units_started']
            and (numbers['batches_pending'] > 0 or numbers['units_started'] == numbers['units_succeeded']),
            'native fixture exporter lost work or invented success')


def running(value: dict, policy: dict, language: str, pid: int, flags: dict, calls: int) -> None:
    """Paused work is known; running queue dimensions remain explicitly unavailable."""
    require(type(calls) is int and calls >= 0 and language in ('c', 'cpp'), 'invalid native fixture call count')
    require(type(value) is dict and set(value) == {'schema_version', 'kind', 'language', 'scope', 'pid',
        'phase', 'sdk_attached', 'policy_sha256', 'selection_sha256', 'source_complete',
        'downstream_receipt', 'otlp_partial_rejection', 'diagnostics', 'controls', 'lifecycle',
        'metric_flush', 'function_accounting', 'span_accounting', 'trace_exports', 'metric_exports'},
        'invalid native fixture running health fields')
    require(type(value['function_accounting']) is dict and 'registered' in value['function_accounting'],
            'native fixture registration is missing')
    registered = value['function_accounting']['registered']
    require(registered in ('0', '1') and (registered == '1' or calls == 0), 'native fixture registration differs')
    expected = {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': language,
        'scope': 'sdk_pipeline', 'pid': pid, 'phase': 'running', 'sdk_attached': True,
        'policy_sha256': retained.digest(policy),
        'selection_sha256': retained.digest({key: policy[key] for key in ('sources', 'functions')}),
        'source_complete': False, 'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable',
        'diagnostics': {'dropped': '0'}, 'controls': value['controls'],
        'lifecycle': value['lifecycle'], 'metric_flush': value['metric_flush'],
        'function_accounting': {'registered': registered, 'started': str(calls), 'ended': str(calls),
            'active': '0', 'closed': False, 'lost': '0', 'invalid': '0', 'metadata_errors': '0'},
        'span_accounting': {'sampled_started': str(calls), 'sampled_ended': str(calls), 'sampled_active': '0',
            'queue_pending': None, 'queue_dropped': None, 'queue_evidence': 'unavailable',
            'processors_observed': 1, 'batch_processors_observed': 1},
        'trace_exports': value['trace_exports'], 'metric_exports': value['metric_exports']}
    same(value, expected); status(value['controls'], pid, flags)
    require(value['lifecycle']['flush'] in ('not_started', 'succeeded'), 'native fixture flush failed')
    same(value['lifecycle'], {'flush': value['lifecycle']['flush'], 'shutdown': 'not_started'})
    same(sorted(value['metric_flush']), ['attempts', 'failed_attempts'])
    count(value['metric_flush']['attempts']); same(value['metric_flush']['failed_attempts'], '0')
    exports(value['trace_exports'], 'spans'); exports(value['metric_exports'], 'metric_points')
    require(count(value['trace_exports']['units_started']) <= calls, 'native fixture exported unplanned spans')


def progress(snapshots: list[dict]) -> None:
    """Later observations cannot erase registered functions or exporter progress."""
    for before, after in zip(snapshots, snapshots[1:]):
        require(count(before['function_accounting']['registered']) <= count(after['function_accounting']['registered']),
                'native fixture registration reset')
        for section in ('trace_exports', 'metric_exports'):
            for key in ('batches_started', 'batches_succeeded', 'units_started', 'units_succeeded'):
                require(count(before[section][key]) <= count(after[section][key]), 'native fixture export counters reset')
