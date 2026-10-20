# Declared HTTP fixtures

Generated runners for all eight language IDs can use a scripted local HTTP service. Every attempt receives fresh response positions, counters and request records. A case reserves one literal loopback URL across its baseline/on repeats, so the application receives the same URL without normalising its output. The result remains **equivalence over these tests and observations**.

## Configure a service

Add a declaration to the TOML policy passed to `plan --config`:

```toml
[[effects.http]]
name = "service"
environment = "APP_SERVICE_URL"
headers = ["host", "x-check"]
responses = [{ status = 201, hex = "00ff", headers = { "Content-Type" = "application/octet-stream" } }]
min_requests = 1
max_requests = 1
max_bytes = 65536
max_header_bytes = 8192
request_timeout_ms = 1000
```

Application code must already read `APP_SERVICE_URL`. The runner supplies a URL such as `http://127.0.0.1:49152` after building the worker. This does not replace hardcoded endpoints, rewrite request data or provide a network sandbox. The listener is reserved for the whole case, while application capture begins separately for each attempt. A new replay or shrink candidate may reserve a different URL; each paired comparison binds its actual fixture URL into its contract.

Declare up to eight services with distinct names and application environment variables. Names and environment rules match [filesystem fixtures](filesystem-effects.md); filesystem and HTTP bindings cannot share an environment variable. The policy rejects compiler, runtime, system and telemetry control variables.

`responses` contains 1 through 256 ordered responses. Each has a status from 200 through 599, optional complete hexadecimal body bytes and an optional bounded ASCII header table. The default is one empty 200 response. All scripted bodies together may contain at most 65536 bytes. Framing, connection and upgrade headers are managed by the fixture. No-content statuses cannot declare a body. HEAD sends the response headers without the scripted body.

`headers` explicitly selects up to 32 distinct lowercase request header names. Matching selected lines are retained verbatim, including wire spelling, whitespace, duplicates and order. Unselected header values are not compared. Select `host` if its literal value matters; it includes the shared case URL's port.

`max_requests` defaults to 64 and accepts 1 through 256. `min_requests` defaults to zero; set it to one or more to require actual calls. Its value cannot exceed the number of scripted responses. Requests beyond either bound are incomplete. `max_bytes` bounds cumulative captured request-body bytes, from zero through 65536. `max_header_bytes` bounds each request line and header section, from 128 through 16384 bytes. `request_timeout_ms` bounds an entire request, from 50 through 5000 ms. The encoded records also count towards the configured combined capture budget.

## Retained observations

Each attempt retains `http-controls.json`, containing the frozen declarations and actual environment bindings, and `http-NAME.json`, containing schema version 1, completion, ordered requests and explicit gaps. Its required byte channel is `http:NAME`.

A request records its method, lossless target bytes, HTTP version, selected raw header lines, complete body bytes, response index and complete offered response bytes. A function returning seven while sending different request bytes therefore produces an observed difference. The offered response record does not prove that application code consumed every byte.

The capture covers the whole application worker, including startup and shutdown. Ordered calls share one request stream; records do not assign requests to particular functions or action boundaries. Ordinary generated tests, replay, export and scalar shrinking reconstruct the same declared service behaviour. Filesystem and HTTP fixtures can be declared together.

## Protocol and failure boundary

This fixture supports a bounded serial HTTP/1.0 and HTTP/1.1 profile with origin-form targets, OPTIONS asterisk form and one request per connection. It sends `Connection: close`. It requires explicit, unambiguous Content-Length framing when a body is present. Transfer coding/chunking, expect/continue, upgrades, CONNECT, buffered pipelining and malformed framing are visible gaps. The profile is narrower than the [HTTP/1.1 message framing specification](https://www.rfc-editor.org/rfc/rfc9112.html) and [HTTP semantics](https://www.rfc-editor.org/rfc/rfc9110.html).

Missing required requests, truncated data, deadlines, response-send failures and exceeded bounds make capture incomplete. Bind failures and unexpected receiver/cleanup failures are tool errors. Shutdown drains pending traffic within its bound; an undrained queue taints the fixture so a later attempt cannot pass using it. Missing or incomplete required channels cannot establish equivalence.

TLS, HTTP/2 and HTTP/3, websockets, multiplexing, general concurrent server behaviour, timing, TCP packet boundaries, complete socket lifecycle, undeclared destinations and remote production services are outside this scope. This protocol does not observe every network effect or isolate the SDK's own network activity. Original application and dependency sources remain unchanged.

## Maintainer qualification

With a qualified built provider and enough free space for private compiler caches, run:

```sh
make generation-http-otelc \
  OTELC_ROOT=/absolute/path/to/otelc \
  REPORT_DIR=/absolute/path/to/new-http-evidence \
  PYTHON=/absolute/path/to/otelc/.venv/bin/python
```

The target builds the consumer and uses Cargo's actual target directory, including `CARGO_TARGET_DIR` overrides. The maintained corpus has eight matching cases, eight deliberately changed request bodies with identical returns and two incomplete Python effects. Its checker requires literal binary request/response and selected-header oracles, actual instrumentation, source preservation, generated/exported suites, missing/incomplete evidence controls and scalar reduction/replay. The incomplete cases make the application's strict gate nonzero; the maintainer script succeeds only when every expected result is verified.

After the original process has terminated, the script's `--resume` option can revalidate completed routes with the same frozen CLI/provider. All four initial execution routes must exist; an unfinished shrink is refused. It neither discards nor restarts incomplete evidence. Copied original-shrink records retain their actual original command, working directory and URL binding, and their sidecars must match the original.

## Qualification status

Focused regressions exercise real plain workers in all eight languages, framing/budget refusals and typed-channel enforcement. A separate development corpus completed 32 paired SDK application launches across the eight default language routes with binary request/response oracles and preserved sources. Final retained generated/exported-suite, same-return difference and shrinking qualification remains pending. A development result does not qualify a release, another provider or a shipping artefact.
