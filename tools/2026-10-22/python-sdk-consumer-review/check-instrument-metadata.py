"""Compare old and corrected metric gates with the installed official SDK."""
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

BASE = Path(__file__).resolve().parent
rows = []
for commit in ("348772d", "7083ac2"):
    filename = BASE / ("python_metrics_" + commit + ".py")
    spec = importlib.util.spec_from_file_location("metric_gate_" + commit, filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    reader = InMemoryMetricReader()
    sdk = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
    controls = module.MetricControls(False, False)
    provider = module.GatedMeterProvider(sdk, controls)
    meter = provider.get_meter("consumer-check", "1.2", "https://example.test/schema", {"role": "check"})
    raw_meter = sdk.get_meter("consumer-check", "1.2", "https://example.test/schema", {"role": "check"})
    instruments = []
    for kind in ("counter", "up_down_counter", "histogram", "gauge"):
        create = getattr(meter, "create_" + kind)
        options = {"explicit_bucket_boundaries_advisory": [.1, .5, 1.]} if kind == "histogram" else {}
        wrapped = create(kind, "s", "A measurement", **options)
        raw = getattr(raw_meter, "create_" + kind)(kind, "s", "A measurement", **options)
        fields = {}
        for field in ("name", "unit", "description", "instrumentation_scope"):
            try:
                fields[field] = getattr(wrapped, field) == getattr(raw, field)
            except AttributeError:
                fields[field] = "AttributeError"
        if commit == "348772d":
            assert all(value == "AttributeError" for value in fields.values()), fields
        else:
            assert all(value is True for value in fields.values()), fields
            assert wrapped.instrumentation_scope is raw.instrumentation_scope
            assert wrapped is create(kind, "s", "A measurement", **options)
        instruments.append({"kind": kind, "public_fields": fields})
    controls.update(collection=True, emission=True)
    meter.create_histogram("histogram", "s", "A measurement",
                           explicit_bucket_boundaries_advisory=[.1, .5, 1.]).record(.25)
    data = reader.get_metrics_data()
    metric = next(metric for resource in data.resource_metrics for scope in resource.scope_metrics
                  for metric in scope.metrics if metric.name == "histogram")
    point = metric.data.data_points[0]
    assert tuple(point.explicit_bounds) == (.1, .5, 1.) and point.count == 1 and point.sum == .25
    assert (metric.unit, metric.description) == ("s", "A measurement")
    sdk.shutdown()
    rows.append({"commit": commit, "module_sha256": hashlib.sha256(filename.read_bytes()).hexdigest(),
                 "instruments": instruments, "actual_histogram_bounds": list(point.explicit_bounds)})
result = {"python": sys.version, "sdk_version": importlib.metadata.version("opentelemetry-sdk"), "rows": rows}
(BASE / "instrument-metadata-correction-review.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
