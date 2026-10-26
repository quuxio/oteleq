"""Independently validate Rust health1 and drop health5 without profile substitution."""

import re

import native_health as common
from native_protocol import fields, require, same


def drops(value: object) -> None:
    """Keep completed and censored Rust owners distinct in closed final accounting."""
    row = fields(value, common.LIFETIMES | {'dropping'}, 'Rust drop health')
    counters = {name: common.count(row[name]) for name in common.LIFETIMES - {'closing', 'closed'} | {'dropping'}}
    require(row['closing'] is True and row['closed'] is True
            and all(counters[name] == 0 for name in ('live', 'dropping', 'ending', 'lost', 'duplicates', 'invalid'))
            and counters['admitted'] == counters['completed'] + counters['censored']
            and (counters['types'] > 0 or counters['admitted'] == 0), 'Rust final drop accounting is incomplete')


def validate(value: object, *, pid: int, policy: str, selection: str, lifetime: bool) -> dict:
    """Bind exact Rust profile/PID/policy/selection before checking common engine units."""
    require(type(lifetime) is bool and type(pid) is int and 1 < pid <= 0x7fffffff
            and all(type(text) is str and re.fullmatch('[a-f0-9]{64}', text) for text in (policy, selection)),
            'invalid Rust final health expectation')
    row = fields(value, common.FIELDS | ({'drop_accounting'} if lifetime else set()), 'Rust final health')
    identity = {'schema_version': 5 if lifetime else 1, 'kind': 'otelc.runtime-health', 'language': 'rust',
        'scope': 'sdk_pipeline', 'pid': pid, 'policy_sha256': policy, 'selection_sha256': selection,
        'phase': 'final', 'sdk_attached': True, 'source_complete': False,
        'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable',
        'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded'}, 'diagnostics': {'dropped': '0'}}
    require(same({key: row[key] for key in identity}, identity),
            'Rust final SDK identity/profile/lifecycle differs from caller expectation')
    common.engines(row, pid)
    require(row['span_accounting']['sampled_ended'] == row['trace_exports']['units_succeeded'],
            'Rust sampled span completion differs from final exported units')
    if lifetime:
        drops(row['drop_accounting'])
    return row
