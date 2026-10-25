"""Independently bind final native SDK health without inventing missing evidence."""

import re

from native_protocol import fields, require, same

FIELDS = {'schema_version', 'kind', 'language', 'scope', 'pid', 'policy_sha256',
          'selection_sha256', 'phase', 'sdk_attached', 'lifecycle', 'controls',
          'metric_flush', 'span_accounting', 'function_accounting', 'diagnostics',
          'trace_exports', 'metric_exports', 'source_complete',
          'downstream_receipt', 'otlp_partial_rejection'}
EXPORTS = {'exporters_observed', 'unit', 'batches_started', 'batches_succeeded',
           'batches_failed', 'batches_pending', 'units_started', 'units_succeeded', 'units_failed'}
FUNCTIONS = {'registered', 'started', 'ended', 'active', 'lost', 'invalid', 'metadata_errors', 'closed'}
SPANS = {'processors_observed', 'batch_processors_observed', 'sampled_started',
         'sampled_ended', 'sampled_active', 'queue_pending', 'queue_dropped', 'queue_evidence'}


def count(value: object) -> int:
    """Native public counters use canonical unsigned decimal strings."""
    require(type(value) is str and re.fullmatch(r'0|[1-9][0-9]{0,19}', value) is not None,
            'invalid native health counter')
    result = int(value)
    require(result < 1 << 64, 'native health counter overflow')
    return result


def exporter(value: dict, unit: str) -> None:
    """Closed final API accounting stays separate from downstream receipt."""
    fields(value, EXPORTS, 'export health')
    require(type(value['exporters_observed']) is int and value['exporters_observed'] in (0, 1)
            and value['unit'] == unit, 'invalid native exporter identity')
    counts = {key: count(value[key]) for key in EXPORTS - {'unit', 'exporters_observed'}}
    require(all(counts[key] == 0 for key in ('batches_failed', 'batches_pending', 'units_failed'))
            and counts['batches_started'] == counts['batches_succeeded']
            and counts['units_started'] == counts['units_succeeded'], 'native exports did not drain')
    require(value['exporters_observed'] == 1 or not any(counts.values()),
            'native unobserved exporter has counters')


def validate(value: dict, *, language: str, pid: int, policy: str, selection: str) -> dict:
    """Require the recorded native final checkpoint, not a legacy health substitute."""
    fields(value, FIELDS, 'final health')
    expected = {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': language,
                'scope': 'sdk_pipeline', 'pid': pid, 'policy_sha256': policy,
                'selection_sha256': selection, 'phase': 'final', 'sdk_attached': True,
                'source_complete': False, 'downstream_receipt': 'unavailable',
                'otlp_partial_rejection': 'unavailable',
                'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded'},
                'diagnostics': {'dropped': '0'}}
    require(language in ('c', 'cpp') and type(pid) is int and pid > 1
            and all(type(text) is str and re.fullmatch('[0-9a-f]{64}', text) for text in (policy, selection))
            and same({key: value[key] for key in expected}, expected), 'native final SDK identity or lifecycle differs')
    control = fields(value['controls'], {'schema_version', 'pid', 'collection', 'emission', 'effective_emission_off'}, 'controls')
    require(type(control['collection']) is type(control['emission']) is bool
            and same(control, {'schema_version': 1, 'pid': pid, 'collection': control['collection'],
                              'emission': control['emission'], 'effective_emission_off': not control['emission']}),
            'native final metric controls differ')
    flush = fields(value['metric_flush'], {'attempts', 'failed_attempts'}, 'flush health')
    count(flush['attempts'])
    require(flush['failed_attempts'] == '0', 'native metric flush failed')
    functions = fields(value['function_accounting'], FUNCTIONS, 'function health')
    for name in FUNCTIONS - {'closed'}:
        count(functions[name])
    require(functions['closed'] is True and functions['started'] == functions['ended']
            and all(functions[key] == '0' for key in ('active', 'lost', 'invalid', 'metadata_errors')),
            'native function accounting is incomplete')
    spans = fields(value['span_accounting'], SPANS, 'span health')
    for name in ('processors_observed', 'batch_processors_observed'):
        require(type(spans[name]) is int and spans[name] in (0, 1), 'native span observer is unavailable')
    for name in SPANS - {'processors_observed', 'batch_processors_observed', 'queue_evidence'}:
        count(spans[name])
    require(spans['processors_observed'] == spans['batch_processors_observed']
            and spans['sampled_started'] == spans['sampled_ended']
            and all(spans[key] == '0' for key in ('sampled_active', 'queue_pending', 'queue_dropped'))
            and spans['queue_evidence'] == 'derived_after_shutdown', 'native trace pipeline is incomplete')
    exporter(value['trace_exports'], 'spans')
    exporter(value['metric_exports'], 'metric_points')
    return value
