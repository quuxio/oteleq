# Observation and comparison contract

## Implemented observations

The [scalar generator](automatic-generation.md#what-is-compared) records typed return/error and before/after state as exact declared byte channels, alongside application stdout/stderr. Python observes supported objects, sequences, dictionaries, exception graphs and declared module globals; Node observes supported plain objects/arrays, Error fields and declared globals. Their codecs preserve supported aliases/cycles, large integers and float bits. C/C++, Rust, Java and Go observe supported scalar results/errors and accessible scalar globals. Python/Node graph capture is bounded at 512 nodes and depth 32; opaque or oversized observations cannot pass.

Receiver construction, imported-module state, hidden fields, mutation-and-reversion between boundaries, filesystem/network observation and arbitrary action sequences remain outside this slice. The fixed diagnostic captures compare stdout/stderr and successful exits with independently declared telemetry expectations; they do not supply these generated state channels. Scope and gaps are retained in each report.

The remaining sections describe the broader proposed observation/graph protocol. Its record shape and typed tags are illustrative; they are not the scalar worker's wire format. The Rust workload comparator currently compares the generated canonical bytes and does not implement arbitrary structural graph matching or field-path difference reporting.

## Application observations

Return values alone are insufficient. A function can return the same number while changing a cache, argument object or global counter differently. Each case compares the following configured dimensions.

| Dimension | Captured boundary |
| --- | --- |
| Outcome | Typed return value, exception/panic/error, exit status, signal or timeout |
| Inputs | Mutable state reachable from the argument roots before and after the action |
| Receiver | Instance fields and reachable objects before and after the action |
| Globals/statics | Declared observable module/package/static roots before and after the action |
| Sequence | State after each declared step, including construction, yields, completion and cleanup |
| Effects | Declared stdout/stderr, filesystem changes, fixture calls, network requests and resource events |
| Telemetry | Separate selected-function witness, decoded OTLP, loss and exporter health |

An ordinary application mutation is allowed when it occurs equivalently in both variants. For example, incrementing a counter from 3 to 4 in both lanes matches. A 3-to-4 baseline change versus a 3-to-5 instrumented change differs even if both calls return 4.

## State roots and graph comparison

Each adapter identifies observable global/static candidates from the actual program model and configuration. Only roots it can inspect through a declared, qualified access path are covered. Unknown/unreachable global state, native opaque objects and unsupported private state remain explicit observation gaps. There is no claim to capture every byte of process memory.

Record each root's declared type, access route and capture mode. Capture a bounded graph that preserves object identity relationships, cycles, shared references, container semantics and deletion/addition. Assign local node IDs within each observation; match graph structure and alias relationships across lanes instead of comparing addresses or runtime-specific identity hashes.

Compare initial snapshots as well as outcomes and final state. If initial states differ, the case is invalid for comparison. A difference report uses a stable path such as `receiver.items[2].status` or `globals.cache.hits` and shows both before/after values.

Read data without invoking getters, descriptors, proxy traps, lazy-loading or arbitrary serialisation methods. If observation itself needs application code, that observer must have a declared side-effect contract and qualification. Otherwise mark the root opaque. Native serializers require typed initialised fields and ownership metadata; raw padding, allocator metadata and uninitialised bytes are excluded as unobservable.

## Boundary snapshots and transient writes

The default capture is `boundary_snapshots`: before and after each declared action. It detects persistent state changes and sequence differences. It cannot detect a write that is restored before the next capture boundary.

Optional `write_events` observation can detect transient writes through qualified language/compiler/debugger or fixture event hooks. Those hooks may themselves change timing and the generated artefact; label such evidence diagnostic and record event scope. Every language adapter declares whether it supports write-event observation. Unsupported event capture cannot be replaced by snapshots while retaining the same claim.

Stateful tests increase the chance of exposing lasting consequences by generating meaningful call sequences. They do not prove the absence of hidden transient mutation.

## Typed value encoding

The proposed version-1 observation protocol uses a typed value representation rather than plain lossy JSON values.

| Kind | Representation and comparison |
| --- | --- |
| `null`, `undefined` | Distinct tags; language-specific absence semantics remain explicit |
| `boolean` | Boolean payload |
| `integer` | Type descriptor plus decimal string, preserving signedness/width and large integers |
| `float` | Type descriptor plus exact bit representation by default, preserving signed zero and NaN representation |
| `string` | UTF-8 text with declared handling for non-Unicode runtime strings |
| `bytes` | Base64 payload and explicit byte length |
| `reference` | Local graph node ID with alias/cycle-preserving comparison |
| `symbol`, `enum` | Qualified runtime/type identity and stable declared payload |
| `opaque` | Reason and type; unobserved, never equal solely because types match |

Sequences, objects, maps and sets are typed graph nodes. Preserve observable ordering, sparse-array holes, key types, field identity and mutable views into shared backing storage where the adapter supports them. Incomplete backing-store alias observation is a reported gap.

Float tolerances, unordered fields and path normalisation require explicit field-scoped policy. The default is exact typed comparison. Store the applied rules and their raw values; no blanket removal of timestamps, random values or `otel*` fields from application output.

Exceptions/errors compare declared type, message and observable payload. Stack traces and source locations have a separately declared source-mapping policy because helper/transform frames may differ. Unexpected application frames or payload changes remain differences. Stable signal/exit observations are retained, but both variants crashing is not a successful functional-equivalence case.

## External effects

Capture only declared effect channels. Separate work directories allow filesystem snapshot/diff for configured roots, including file content and declared metadata. A filesystem snapshot misses write-and-restore events; use qualified event observation if that matters.

Use deterministic fixture services to record requests/responses, arguments, call counts and specified order. A request equivalence result applies to that fixture boundary, not to an unobserved real database or remote service. External interactions that bypass capture are gaps.

stdout/stderr default to exact application bytes. Give the harness a dedicated observation channel and telemetry a dedicated receiver; neither may be mixed into application output and then removed by a broad text filter. Explicit runtime diagnostics can be separated only when their origin is reliably identified.

Resource operations such as close/drop/destructor events use declared fixture hooks or legal observers. Allocation addresses, GC timing and general scheduling are not assumed stable. Resource budgets and leak checks can supplement functional observations without being mislabelled value equivalence.

## Telemetry boundary

Instrumentation-owned runtime/exporter state is tracked separately through known identities from the provider. Exclusion is specific to those components; application objects with an `otel` name remain application observations. Any instrumentation mutation of application state remains a difference.

Decode actual OTLP messages in an independent bounded receiver. Verify selected function activity, resource identity and expected signal kinds with adapter-specific rules. Timings, IDs, timestamps and delivery counts can legitimately vary; telemetry content equality is a separate semantic test, not the application comparator's default assertion.

Telemetry-on execution includes real encoding, batching, export and shutdown. Record missing/dropped signals and exporter failures. A missing expected instrumentation witness yields incomplete evidence. Queue saturation/failure runs explicitly identify their expected loss while continuing to compare application observations.

## Bounds and failures

Bound graph depth, node count, value sizes, effects, case duration, worker memory, output volume and shutdown. Any truncated or missing required dimension yields `inconclusive` and records the limit; it cannot become a pass because prefixes match.

Record capture completion independently for every root/channel. Optional unobserved dimensions remain gaps even when the user permits the run to complete. Tool/codec errors, missing case messages and protocol-version mismatches are tool failures.

## Illustrative observation records

The [baseline example](../examples/observations/baseline.json) and [instrumented example](../examples/observations/instrumented-on.json) describe the same valid fixture and return value. Their receiver counters differ. They are hand-written protocol examples, not evidence from an executed application.

The proposed graph comparator must report `different_observed` at `receiver.calls`, with baseline `3 -> 4` and instrumented `3 -> 5`. It must also state that only the receiver root was captured and globals/effects were not observed. These records are acceptance fixtures for that richer protocol. The implemented scalar qualification separately demonstrates a same-return/different-global-object mutation through actual paired execution.
