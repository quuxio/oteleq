"""Join the maintained lifetime corpus's raw receipt to literal final SDK health.

The independent oracle imports no producer or product receipt renderer. Original
host/compiler/file identity auditing remains a separate caller responsibility.
"""

from pathlib import Path
import re
import tomllib

import native_lifetime_otlp as otlp
import native_prepared_receipt as records
from native_prepared_otlp import BOUNDS, require, same


def policy(folder: Path, entry: dict) -> dict:
    """Reconstruct the declared fixture policy, retaining caller-selected endpoints."""
    language = entry['language']
    require(language in ('c', 'cpp'), 'lifetime audit requires c or cpp')
    extension = 'cpp' if language == 'cpp' else 'c'
    function = 'selected(int)' if language == 'cpp' else 'selected'
    same(entry['path'], 'src/app.' + extension)
    same(entry['otelc_function'], function)
    same(entry['otelc_runtime_function'], entry['path'] + '::' + function)
    value = tomllib.loads((folder / 'policy.toml').read_text())
    service = value['resource']['service_name']; endpoint = value['export']['endpoint']
    require(type(service) is str and re.fullmatch(r'oteleq-gen-[a-f0-9]{32}', service) is not None,
            'foreign lifetime corpus service')
    match = re.fullmatch(r'http://127\.0\.0\.1:([1-9][0-9]{0,4})', endpoint) if type(endpoint) is str else None
    require(match is not None and int(match[1]) <= 65535, 'foreign lifetime corpus endpoint')
    same(value, {'schema_version': 3, 'languages': [language], 'resource': {'service_name': service},
        'export': {'endpoint': endpoint, 'interval_ms': 1000, 'timeout_ms': 1000, 'shutdown_timeout_ms': 10000},
        'sources': {'include': ['build/compile_commands.json', 'include/item.h',
                                'src/app.' + extension, 'src/keep.' + extension], 'exclude': []},
        'functions': {'include': [function], 'exclude': []},
        'metrics': {'collection': True, 'emission': True, 'histogram_boundaries_seconds': BOUNDS},
        'traces': {'enabled': True, 'sample_ratio': 1.0},
        'lifetimes': {'enabled': True, 'include': ['Item'], 'exclude': [], 'max_live': 4096, 'release_methods': ['close']},
        'context': {'tasks': False, 'http': False}, 'benchmark': {'iterations': 10000, 'samples': 15, 'warmup': 5}})
    return value


def health(value: dict, expected_policy: dict, language: str, pid: int, raw: dict) -> None:
    """All closed final counters and API units must explain the raw transport."""
    require(type(pid) is int and 1 < pid < 2**31, 'invalid native lifetime SDK PID')
    accounting = {'types': '1', 'admitted': '1', 'completed': '1', 'live': '0', 'ending': '0',
                  'censored': '0', 'lost': '0', 'duplicates': '0', 'invalid': '0', 'closing': True, 'closed': True,
                  'destroying' if language == 'cpp' else 'releasing': '0'}
    selection = {key: expected_policy[key] for key in ('sources', 'functions')}
    selection['lifetimes'] = {key: expected_policy['lifetimes'][key] for key in ('enabled', 'include', 'exclude')}
    same(value, {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': language, 'pid': pid,
        'phase': 'final', 'scope': 'sdk_pipeline', 'sdk_attached': True, 'source_complete': False,
        'policy_sha256': records.digest(expected_policy),
        'selection_sha256': records.digest(selection),
        'controls': {'schema_version': 1, 'pid': pid, 'collection': True, 'emission': True, 'effective_emission_off': False},
        'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded'},
        'function_accounting': {'registered': '1', 'started': '1', 'ended': '1', 'active': '0',
                                'closed': True, 'lost': '0', 'invalid': '0', 'metadata_errors': '0'},
        'object_accounting' if language == 'cpp' else 'resource_accounting': accounting,
        'span_accounting': {'sampled_started': '2', 'sampled_ended': '2', 'sampled_active': '0',
            'queue_dropped': '0', 'queue_pending': '0', 'queue_evidence': 'derived_after_shutdown',
            'processors_observed': 1, 'batch_processors_observed': 1},
        'trace_exports': value['trace_exports'], 'metric_exports': value['metric_exports'],
        'metric_flush': value['metric_flush'], 'diagnostics': {'dropped': '0'},
        'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'})
    records.exports(value['trace_exports'], 'spans', 2, raw['trace_requests'])
    records.exports(value['metric_exports'], 'metric_points', raw['metric_points'], raw['metric_requests'])
    same(sorted(value['metric_flush']), ['attempts', 'failed_attempts'])
    require(type(value['metric_flush']['attempts']) is str and
            re.fullmatch(r'[1-9][0-9]{0,19}', value['metric_flush']['attempts']) is not None, 'missing final lifetime flush')
    same(value['metric_flush']['failed_attempts'], '0')


def verify(folder: Path, entry: dict, witness, *, plain: bool) -> dict | None:
    """Decode all original bytes before joining any producer-verified receipt."""
    selected = policy(folder, entry)
    request = records.read(folder / 'native-runtime/native-request.json')
    same(request['plain'], plain); same(request['policy'], selected)
    observations = [{'type_usr': 'c:@S@Item', 'name': 'Item', 'creation_path': [0], 'release_path': [0],
                     'complete': True, 'exception_exit': False if entry['language'] == 'cpp' else None}]
    before = {'schema_version': 1, 'kind': 'oteleq.native.lifetime-before-build',
              'roots': [entry['otelc_runtime_function']], 'observations': observations}
    same(records.read(folder / 'expected-lifetimes-before-build.json'), before)
    intent = records.read(folder / 'expected-lifetimes.json')
    same(intent['roots'], before['roots']); same(intent['observations'], observations)
    same(intent['native_profile'], 'object' if entry['language'] == 'cpp' else 'resource')
    raw = otlp.receipt(folder, records.read, entry['language'], selected['resource']['service_name'],
                       entry['otelc_runtime_function'], plain=plain)
    checkpoint = folder / 'native-runtime/app/health.json'
    if plain:
        require(witness is None and not checkpoint.exists(), 'plain lifetime fixture has SDK evidence')
        return None
    pid = records.read(folder / 'native-runtime/native-application-start.json')['pid']
    final = records.read(checkpoint)
    health(final, selected, entry['language'], pid, raw)
    verified = records.read(folder / 'native-verified-lifetimes.json')
    same({key: verified[key] for key in ('functions', 'spans', 'lifetimes', 'metric_points', 'raw_otlp_sha256')},
         {key: raw[key] for key in ('functions', 'spans', 'lifetimes', 'metric_points', 'raw_otlp_sha256')})
    same(verified['sdk_pid'], pid); same(verified['health'], final)
    expected_witness = {'decoder': 'independent native lifetime receipt with owned health1',
        'functions': raw['functions'], 'spans': 1, 'raw_otlp_sha256': raw['raw_otlp_sha256'],
        'losses': {'function_lost': 0, 'lifetime_lost': 0, 'metadata_errors': 0,
                   'queue_dropped': 0, 'diagnostic_dropped': 0}, 'pending': 0}
    same(witness, expected_witness)
    same(verified['losses'], expected_witness['losses']); same(verified['pending'], 0)
    return raw
