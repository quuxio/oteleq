# Retained OTLP/HTTP capture and forwarding

<!-- markdownlint-disable MD013 -->

`examples/otelc_capture_forward.py` provides an opt-in receiver for diagnostic qualification. It retains original request and Collector response entities while forwarding to one caller-held loopback HTTP origin. The default capture receiver still acknowledges locally. Neither route admits a language/provider profile or proves application equivalence.

Use a pinned checkout and put its `examples/` directory first on the Python import path. Keep the helper, `otelc_capture.py`, `otelc_collection.py` and `otelc_resource.py` bound to that source revision. No native compiler or SDK build is required to import the helper.

```python
from pathlib import Path
from otelc_capture_forward import forwarding_receiver

with forwarding_receiver(
    "http://127.0.0.1:4320",
    Path("/absolute/new/capture-directory"),
    max_requests=4096,
    max_bytes=32 * 1024**2,
    allow_chunked=True,
) as captured:
    endpoint = captured.endpoint
    # Configure the diagnostic application and benchmark driver with endpoint.
    # Run them, then finish their exporters and wait for both processes to exit.

captured.require_complete()
receipt = captured.receipt
```

The output parent must already exist. The helper creates a new mode0700 directory and exclusive mode0600 files. Existing output refuses. `receipt` is available after context exit and returns a fresh JSON view. `require_complete()` rechecks original helper inputs, entity/manifest bytes, file facts and the closed output denominator. Edited and restored files cannot refresh the receipt.

## Transport and limits

Only `/v1/traces` and `/v1/metrics` POST requests are accepted. Request framing uses the existing fixed-length parser or explicitly enabled bounded chunks. Transfer decoding preserves the entity bytes; chunk boundaries, wire packets and content decompression are outside this record. Request content encoding remains identity-only. The destination must be a literal loopback HTTP origin, without credentials, path, query or fragment. The helper uses a direct connection and does not use environment proxies, follow redirects or retry.

Each request entity is limited to 1 MiB. `max_bytes` independently bounds total request and original upstream response entity bytes. Each response is also bounded by `max_response_bytes` (default 1 MiB). Essential headers are limited to 8 KiB per side. The complete incoming header block and upstream status/header block each have an 8 KiB limit. Records are limited by `max_requests`, which cannot exceed 4,096. Protocol error text is bounded separately. The manifest records these limits. The receiver has a two-second body deadline and an absolute incoming request watchdog. `upstream_timeout` (default two seconds, maximum ten) bounds each upstream exchange, including stalled headers and EOF-framed bodies. An EOF before either header terminator refuses. Context exit drains the accepted handler, then interrupts stalled owned sockets and records any incomplete drain.

The helper records the original numeric Collector status and essential media, framing and retry headers. A successful relay references the same retained response entity; it does not store a second copy. Non-success Collector statuses are relayed with their original entities and make completion fail. Connection errors, timeouts, ambiguous/truncated responses and byte-limit failures produce local failure responses, never an invented HTTP200. Incomplete original upstream entities remain explicitly incomplete; malformed/incomplete client entities are not represented as complete requests. Client receipt of a written response is not observed.

Chunked responses require the final blank trailer line. Trailer parsing has a separate 8 KiB budget. Chunk framing and trailer fields are excluded from the retained decoded response entity.

## Retained result

`forward-capture.json` uses schema1 and kind `oteleq.otlp-http-forward`. It includes the fixed destination, endpoint, limits, source hashes, closed/drained state, error and quota counters, and bounded events. Each event links a complete request entity, original upstream status/headers/entity/completeness, attempted client response, forwarding errors and monotonic timing. Separate binary entity files have their byte lengths and SHA256 hashes in the manifest. The final manifest is published without overwriting an existing file. Authentication headers and live SDK control descriptors are not retained.

HTTP forwarding completion is separate from OTLP partial rejection and downstream ingestion. A Collector HTTP200 can contain a partial-success response. This helper preserves that entity but does not interpret it. Qualification must separately join decoded units, final SDK health and actual current-run Collector/Prometheus/Grafana data. Timing and process/resource claims belong to the benchmark's own records.

Run `make capture-forward-check` for controlled loopback forwarding, failure, deadline, budget and evidence-integrity controls plus existing capture-framing regressions. These checks use Python fixtures; they do not build or qualify an SDK, target application, shipping artefact or a new language profile.
