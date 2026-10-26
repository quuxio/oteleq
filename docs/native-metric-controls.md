# Native live metric controls

<!-- markdownlint-disable MD013 -->

Status: the [18-shard exact-revision qualification](qualification/native-workflows-2026-10-26.json) includes all eight native metric shards, with 944 distinct application launches, 472 instrumented receipts, 84 promotion reports and 392 altered-evidence refusals. This covers the named diagnostic C/C++ free-function profiles and all four startup states; broader callable/build profiles remain open.

The explicit C/C++ prepared function profile can declare serial calls with a metric state for each call. One unchanged application process and build executes the schedule. Collection and emission change independently; tracing remains enabled. The controller restores both metric flags and flushes before the same application finishes.

## Declare calls

Use a matching prepared native SDK and LLVM installation as described in the [prepared provider](native-prepared-provider.md). A free scalar function can use the common sequence configuration without a receiver:

```toml
schema_version = 1
languages = ["cpp"]

[adapters.cpp]
backend = "prepared"
sdk_build = "/absolute/otelc/build/context-sdk"
sdk_source_profile = "resource-v1"

[limits]
case_timeout_ms = 20000

[functions]
include = ["selected"]

[[fixtures]]
function = "selected"
cases = [[7]]
sequence = [
  { action = "call", arguments = "case", metrics = { collection = true, emission = true } },
  { action = "call", arguments = "case", metrics = { collection = false, emission = true } },
  { action = "call", arguments = "case", metrics = { collection = true, emission = false } },
  { action = "call", arguments = "case", metrics = { collection = false, emission = false } },
]
```

Select `languages = ["c"]` and `[adapters.c]` for a C source target. Each schedule has 1 to 32 calls and must include a collection-on/emission-on positive call. The first call can request any of the four states; its flags become the initial SDK policy before application execution. Every call currently uses the same concrete case arguments. Declare [independent baseline expectations](expected-returns.md) on individual calls where needed, including supported C++ errors.

An expected C++ exception requires the complete declaration, for example `expected_baseline = { kind = "error", category = "exception", type = "cpp.std::runtime_error" }` on the throwing call. A bare error kind is invalid. The maintained qualifier validates all 28 generated workload/start configurations through the public policy reader before their fixture contracts are accepted by the component gate.

Each disabled state is held for at least one full one-second export interval. The original case timeout includes these holds, transport queries and application calls. Increase it for longer schedules. A timeout is incomplete evidence and cannot become an equivalent result.

## Observations and receipt

The neutral generated driver calls the unchanged compiler-bound invocation helper. It records a separate private ABI/before/outcome/after frame for each call, including intermediate global mutations and supported C++ exception bytes. Checkpoints preserve `errno` around observer operations. No developer source, dependency, annotation or import change is required.

The driver closes each private frame before it publishes its after checkpoint. Ready/resume data files have mode 0600; their empty publication directories have mode 0700. The host binds a nonce, ordered phases, the original directory and file identities, and the actual native application PID from the existing pre-exec owner. Later replacement, writes, links, wrong phases, missing files and unsafe permissions refuse.

The host-created `observation` container packages the exact original frame bytes as hexadecimal, with caller-owned step IDs. It does not rewrite application values. Original frames remain available under `native-rendezvous/`. The common typed observation includes every step, so equal final results and restored final globals cannot hide an observed intermediate difference.

Immutable `native-live-N.json` snapshots and final `native-controls.json` retain bounded control replies without the SDK endpoint authentication token. Running health keeps unavailable queue observations as null. It checks the same PID, policy and selection, complete paused function work, and failures separately from final shutdown health.

The live receiver and receipt reader share a 4,096-request limit. This reserves repeated metric flushes, trace batches, periodic exports and final drain; it does not increase the existing raw byte limit. The ordinary single-call receiver limit is unchanged.

The direct raw-OTLP reader checks serial roots and recursive child trees. Each root's error status must match its corresponding scalar outcome. Traces count every selected call. Function measurements count only calls made while collection is enabled. Emission-disabled collected measurements must appear after restoration. Complete cumulative counters and histogram samples are retained; disabled receiver windows, exporter counter resets, missing roots and wrong final SDK units refuse.

Results remain **equivalence over these tests and observations**. These diagnostic workers do not establish behaviour of a different shipping artefact.

## Maintainer checks and remaining qualification

```sh
make native-metric-control-check PYTHON=/absolute/path/to/python \
  OTELC_CLANG=/absolute/llvm/bin/clang \
  OTELC_CLANGXX=/absolute/llvm/bin/clang++
```

The target enforces 80% statement coverage separately for the five new Python modules. Checks use literal SDK replies, real private files, mocked process ownership, independently authored protobuf values and strict C/C++ syntax checks. They do not build or run an SDK application.

Both languages and all four startup states complete the recorded generated, framework, replay, detached, reduced and promoted workflows. Independent readers check prescribed state/result/error observations, complete raw telemetry, final SDK units and altered-evidence refusals. The original source, tested CLI bytes, SDK products and archived captures remain bound to their recorded identities; another source/provider needs separate qualification.

The [workflow qualifier](native-metric-workflows.md) implements those routes with independent complete frame/health/OTLP readers. Its component checks remain separate from the published original application corpus and retained-byte audit.

Prepared receivers, native object/resource live schedules, variable per-call arguments, general asynchronous actions, shipping artefacts and invocation-scoped attribution require further integration and qualification. Requested unsupported profiles remain visible refusals.
