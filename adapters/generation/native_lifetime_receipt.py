"""Join caller lifetime expectations to owned final health and literal raw OTLP."""

from collections import Counter, defaultdict
import hashlib

import native_execution
import native_health
import native_lifetime_intent as caller
import native_lifetime_metrics as measurements
from native_protocol import require, same
import native_telemetry as telemetry
import otelc_capture as capture


def call_paths(spans: dict) -> dict:
    """Assign declared serial paths only where complete sibling ordering is visible."""
    children = defaultdict(list)
    for key, span in spans.items():
        parent = (span.trace_id, span.parent_span_id) if span.parent_span_id else None
        children[parent].append(key)
    for siblings in children.values():
        siblings.sort(key=lambda key: spans[key].start_time_unix_nano)
        require(len({spans[key].start_time_unix_nano for key in siblings}) == len(siblings)
                and all(spans[first].end_time_unix_nano <= spans[second].start_time_unix_nano
                        for first, second in zip(siblings, siblings[1:])),
                'ambiguous or overlapping native serial call boundaries')
    pending = [((index,), key) for index, key in enumerate(children[None])]
    paths = {}
    while pending:
        path, key = pending.pop()
        require(len(path) <= 64, 'native serial call depth exceeds lifetime budget')
        paths[path] = spans[key]
        pending.extend(((*path, index), child) for index, child in enumerate(children[key]))
    require(len(paths) == len(spans), 'native lifetime call graph is incomplete')
    return paths


def attributes(rows) -> dict:
    """Keep lifetime bool attributes distinct from string identities."""
    result = {}
    for row in rows:
        kind = row.value.WhichOneof('value')
        require(row.key not in result and kind in ('string_value', 'bool_value'),
                'invalid native lifetime span attribute')
        result[row.key] = getattr(row.value, kind)
    return result


def observation(span, expected: caller.Observation, number: int, paths: dict, boundary: str) -> dict:
    """Creation links and release/censoring boundaries must match caller intent."""
    end = boundary if expected.complete else 'shutdown_censored'
    labels = {'type': expected.name, 'boundary': end, 'otelc.lifetime.complete': expected.complete,
              'otelc.lifetime.instance': str(number)}
    if expected.exception_exit is not None:
        labels['otelc.destructor.exception_exit'] = expected.exception_exit
    require(same(attributes(span.attributes), labels) and span.name == expected.name + ' lifetime'
            and not span.parent_span_id and span.kind == 1 and span.status.code == 0
            and not span.status.message and not span.trace_state and span.flags & 1
            and not span.events and len(span.links) == 1
            and span.dropped_attributes_count == span.dropped_events_count == span.dropped_links_count == 0,
            'native lifetime trace differs from its declared instance or release kind')
    creation = paths.get(expected.creation_path)
    require(creation is not None and creation.start_time_unix_nano <= span.start_time_unix_nano
            <= creation.end_time_unix_nano, 'lifetime creation lies outside the declared selected call')
    link = span.links[0]
    require(link.trace_id == creation.trace_id and link.span_id == creation.span_id
            and not link.trace_state and not link.attributes and not link.dropped_attributes_count
            and link.flags == 0, 'native lifetime creation link differs from the selected call')
    if expected.complete:
        release = paths.get(expected.release_path)
        require(release is not None and release.start_time_unix_nano <= span.end_time_unix_nano
                <= release.end_time_unix_nano, 'lifetime release lies outside the declared selected call')
    else:
        require(span.end_time_unix_nano >= max(value.end_time_unix_nano for value in paths.values()),
                'native lifetime was censored before selected calls completed')
    return {**expected.data(), 'instance': str(number), 'boundary': end,
            'duration_ns': span.end_time_unix_nano - span.start_time_unix_nano,
            'trace_id': span.trace_id.hex(), 'span_id': span.span_id.hex(),
            'creation_trace_id': creation.trace_id.hex(), 'creation_span_id': creation.span_id.hex()}


def traces(intent: caller.Intent, bodies: tuple, language: str, service: str) -> tuple:
    """Decode every span once; lifetime roots cannot hide in the function tree."""
    functions, lifetimes, identities = [], [], set()
    for span in telemetry.trace_values(bodies, language, service):
        key = capture.span_identity(span)
        require(key not in identities and len(identities) < telemetry.MAX_SPANS,
                'duplicate or excessive native lifetime/function span')
        identities.add(key)
        (functions if any(row.key == 'function' for row in span.attributes) else lifetimes).append(span)
    graph, errors = telemetry.function_graph(iter(functions), intent.roots)
    paths = call_paths(graph)
    require(len(lifetimes) == len(intent.observations), 'missing or extra declared native lifetime spans')
    numbered = {}
    function_traces = {span.trace_id for span in functions}
    for span in lifetimes:
        instance = attributes(span.attributes).get('otelc.lifetime.instance')
        require(instance not in numbered and span.trace_id not in function_traces,
                'duplicate lifetime instance or non-independent lifetime trace')
        native_health.count(instance)
        numbered[instance] = span
        function_traces.add(span.trace_id)
    require(set(numbered) == {str(index + 1) for index in range(len(intent.observations))},
            'native lifetime admission sequence differs from caller expectations')
    boundary = 'destructor_entry' if intent.launch.intent.lifetime_kind() == 'object' else 'free_entry'
    observations = [observation(numbered[str(index)], expected, index, paths, boundary)
                    for index, expected in enumerate(intent.observations, 1)]
    return dict(Counter(span.name for span in functions)), errors, len(identities), observations


def metrics(intent: caller.Intent, bodies: tuple, language: str, service: str, names: dict,
            errors: Counter, observations: list) -> int:
    """Account for function and lifetime instruments without discarding either."""
    policy = intent.launch.intent.policy()
    bounds = policy['metrics']['histogram_boundaries_seconds']
    enabled = policy['metrics']['collection'] and policy['metrics']['emission']
    functions, lifetimes = [], []
    for value in telemetry.metric_values(bodies, language, service):
        (lifetimes if value.name in measurements.INSTRUMENTS else functions).append(value)
        require(len(functions) + len(lifetimes) <= telemetry.MAX_POINTS,
                'native lifetime instrument budget exceeded')
    count = telemetry.function_metrics(iter(functions), names, errors, bounds, enabled)
    boundary = 'destructor_entry' if intent.launch.intent.lifetime_kind() == 'object' else 'free_entry'
    duration_values = defaultdict(list)
    for row in observations:
        duration_values[row['name'], row['boundary']].append(row['duration_ns'] / 1_000_000_000)
    count += measurements.validate(iter(lifetimes), intent.observations, boundary, bounds, enabled, duration_values)
    require(count <= telemetry.MAX_POINTS, 'combined native metric point budget exceeded')
    return count


def health(completed: native_execution.Execution, intent: caller.Intent, names: dict,
           spans: int, points: int) -> dict:
    """Final pipeline units and lifetime accounting must agree with the raw receipt."""
    value = completed.health.value()
    policy = intent.launch.intent.policy()
    life = value[intent.launch.intent.lifetime_kind() + '_accounting']
    expected = {'types': len({row.type_usr for row in intent.observations}),
                'admitted': len(intent.observations), 'completed': sum(row.complete for row in intent.observations),
                'censored': sum(not row.complete for row in intent.observations)}
    require(all(life[key] == str(number) for key, number in expected.items())
            and all(value['controls'][key] is policy['metrics'][key] for key in ('collection', 'emission'))
            and value['function_accounting']['registered'] == str(len(names))
            and value['function_accounting']['started'] == str(sum(names.values()))
            and value['span_accounting']['sampled_started'] == str(spans)
            and value['trace_exports']['units_succeeded'] == str(spans)
            and value['metric_exports']['units_succeeded'] == str(points),
            'native lifetime final SDK accounting differs from expected instances or raw receipt')
    return value


def witness(completed: native_execution.Execution, intent: caller.Intent, bodies: list) -> dict | None:
    """Qualify fixed startup states; live changes require separate checkpoints."""
    require(type(completed) is native_execution.Execution and type(intent) is caller.Intent
            and completed.started.launch is intent.launch, 'native lifetime receipt has another owned launch')
    completed.verify(); intent.verify()
    require(type(bodies) is list, 'native lifetime receipt requires the original captured body list')
    frozen = tuple(bodies)
    require(len(frozen) <= 4096 and all(type(row) is tuple and len(row) == 2
            and row[0] in (capture.TRACE_PATH, telemetry.METRIC_PATH)
            and type(row[1]) is bytes and bool(row[1]) for row in frozen)
            and sum(len(row[1]) for row in frozen) <= telemetry.MAX_BYTES,
            'invalid native lifetime capture route or byte budget')
    if intent.launch.intent.plain:
        require(not frozen and completed.health is None, 'plain lifetime application emitted SDK evidence')
        return None
    policy = intent.launch.intent.policy()
    require(policy['traces']['enabled'] is True and type(policy['traces']['sample_ratio']) in (int, float)
            and policy['traces']['sample_ratio'] == 1, 'lifetime receipt requires complete selected traces')
    language = intent.launch.intent.context().language
    service = policy['resource']['service_name']
    names, errors, spans, observations = traces(intent, frozen, language, service)
    points = metrics(intent, frozen, language, service, names, errors, observations)
    final = health(completed, intent, names, spans, points)
    digest = hashlib.sha256()
    for route, body in frozen:
        digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
    result = {'decoder': 'independent native lifetime receipt with owned health1',
        'raw_otlp_sha256': digest.hexdigest(), 'caller_intent': intent.record.file.gate_identity(),
        'functions': names, 'spans': spans, 'lifetimes': observations, 'metric_points': points,
        'sdk_pid': completed.started.owner.application_pid,
        'scope': intent.record.value()['scope'], 'health': final,
        'losses': {'function_lost': 0, 'lifetime_lost': 0, 'metadata_errors': 0,
                   'queue_dropped': 0, 'diagnostic_dropped': 0}, 'pending': 0}
    completed.verify(); intent.verify()
    return result
