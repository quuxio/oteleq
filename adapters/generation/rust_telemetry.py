"""Join caller-frozen Rust calls to owned completion and direct OTLP receipt."""

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

import native_inputs as inputs
from native_protocol import digest, require, same
import native_session
import native_telemetry as wire
import otelc_capture as capture
import rust_build_recipe
import rust_execution
import rust_health
import rust_prepared


def expected(launch: rust_prepared.Prepared, roots: tuple[str, ...]) -> dict:
    """Resolve call names against accepted compiler discovery before execution."""
    require(type(launch) is rust_prepared.Prepared, 'Rust receipt needs accepted preparation')
    launch.verify()
    require(not launch.intent.source().intent.lifetime,
            'Rust drop receipt requires independent lifetime observations')
    require(type(roots) is tuple and 1 <= len(roots) <= 64
            and all(type(name) is str and 0 < len(name.encode()) <= 4096 and '\0' not in name
                    for name in roots)
            and sorted(set(roots)) == launch.intent.source().intent.selected(),
            'Rust expected calls differ from independently selected source functions')
    return {'schema_version': 1, 'kind': 'oteleq.rust.call-intent', 'roots': list(roots),
            'preparation': {name: record.file.gate_identity() for name, record in
                zip(rust_prepared.RECORDS, launch.records, strict=True)},
            'scope': 'Declared synchronous serial selected call trees; no general action/thread attribution'}


@dataclass(frozen=True)
class Intent:
    """An original private publication retains expected calls through execution."""

    launch: rust_prepared.Prepared
    roots: tuple[str, ...]
    record: inputs.Record

    def verify(self) -> None:
        """A changed or restored expectation cannot be adopted after launch."""
        self.record.verify()
        require(same(self.record.value(), expected(self.launch, self.roots)),
                'Rust original caller expectations changed')


def freeze(launch: rust_prepared.Prepared, roots: tuple[str, ...], path: Path) -> Intent:
    """Publish expected calls in a new external file while preparation is unused."""
    value = expected(launch, roots)
    require({child.name for child in launch.intent.runtime.iterdir()} == set(rust_prepared.RECORDS),
            'Rust call expectations must precede supervisor execution')
    source = launch.intent.source().intent
    protected = (source.project, source.output, source.sdk.root, source.sdk.directory,
                 source.tools.directory, source.tools.compiler.sysroot,
                 launch.intent.build.intent.output, launch.intent.runtime,
                 launch.intent.python.path.parent, launch.intent.interpreter.path.parent)
    require(isinstance(path, Path) and path.is_absolute() and '..' not in path.parts
            and path.parent == path.parent.resolve(strict=True) and path.parent.is_dir()
            and not path.exists() and not path.is_symlink()
            and not any(capture.path_within(path, root) for root in protected),
            'Rust call expectations need a new external private file')
    result = Intent(launch, roots, native_session.publish(path, value))
    result.verify()
    return result


def observe(bodies: list, policy: dict, selected: tuple[str, ...], roots: tuple[str, ...],
            health: dict, *, pid: int) -> dict:
    """Decode a fixed-state function receipt; this alone makes no OS ownership claim."""
    require(type(selected) is tuple and type(roots) is tuple and 1 <= len(roots) <= 64
            and all(type(name) is str and 0 < len(name.encode()) <= 4096 and '\0' not in name
                    for name in roots)
            and same(list(selected), sorted(set(roots))), 'invalid Rust receipt function denominator')
    require(policy['lifetimes']['enabled'] is False,
            'Rust drop receipt requires independent lifetime observations')
    require(policy['traces']['enabled'] is True and type(policy['traces']['sample_ratio']) in (int, float)
            and policy['traces']['sample_ratio'] == 1,
            'Rust receipt requires complete selected traces')
    metrics = policy['metrics']
    bounds = metrics['histogram_boundaries_seconds']
    service = policy['resource']['service_name']
    require(type(service) is str and 0 < len(service.encode()) <= 4096 and '\0' not in service
            and all(type(metrics[key]) is bool for key in ('collection', 'emission'))
            and type(bounds) is list and len(bounds) <= 4096
            and all(type(n) in (int, float) and math.isfinite(n) and n >= 0 for n in bounds)
            and all(a < b for a, b in zip(bounds, bounds[1:])), 'invalid Rust receipt policy')
    rust_health.validate(health, pid=pid, policy=digest(policy),
        selection=digest(rust_build_recipe.selection(policy)), lifetime=False)
    require(type(bodies) is list and len(bodies) <= 4096
            and all(type(row) is tuple and len(row) == 2 and type(row[0]) is str
                    and row[0] in (capture.TRACE_PATH, wire.METRIC_PATH)
                    and type(row[1]) is bytes and bool(row[1]) for row in bodies)
            and sum(len(body) for _, body in bodies) <= wire.MAX_BYTES,
            'invalid Rust telemetry route or capture budget')
    names, errors, spans = wire.traces(bodies, 'rust', service, roots)
    points = wire.metrics(bodies, 'rust', service, names, errors, bounds,
                          metrics['collection'] and metrics['emission'])
    require(all(health['controls'][key] is metrics[key] for key in ('collection', 'emission'))
            and health['function_accounting']['registered'] == str(len(selected))
            and health['function_accounting']['started'] == str(spans)
            and health['span_accounting']['sampled_started'] == str(spans)
            and health['trace_exports']['units_succeeded'] == str(spans)
            and health['metric_exports']['units_succeeded'] == str(points),
            'Rust final SDK unit counters differ from expected calls or direct receipt')
    raw = hashlib.sha256()
    for route, body in bodies:
        raw.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
    return {'decoder': 'independent Rust function receipt with health1',
            'raw_otlp_sha256': raw.hexdigest(), 'functions': names, 'spans': spans,
            'metric_points': points, 'sdk_pid': pid,
            'received': {'spans': spans, 'metric_points': points,
                'trace_requests': sum(route == capture.TRACE_PATH for route, _ in bodies),
                'metric_requests': sum(route == wire.METRIC_PATH for route, _ in bodies)},
            'losses': {'function_lost': 0, 'metadata_errors': 0,
                       'queue_dropped': 0, 'diagnostic_dropped': 0}, 'pending': 0,
            'scope': 'Expected serial calls and received entities; no Collector forwarding or shipping proof',
            'health': health}


def witness(completed: rust_execution.Execution, intent: Intent, bodies: list) -> dict | None:
    """Require original prelaunch expectations and owned completion before receipt."""
    require(type(completed) is rust_execution.Execution and type(intent) is Intent
            and completed.started.launch is intent.launch, 'Rust receipt has another owned launch')
    completed.verify()
    intent.verify()
    if intent.launch.intent.plain:
        require(type(bodies) is list and not bodies and completed.health is None,
                'plain Rust worker emitted SDK evidence')
        return None
    policy = intent.launch.intent.policy()
    result = observe(bodies, policy, tuple(intent.launch.intent.source().intent.selected()),
                     intent.roots, completed.health.value(), pid=completed.started.owner.application_pid)
    result['caller_intent'] = intent.record.file.gate_identity()
    completed.verify()
    intent.verify()
    return result
