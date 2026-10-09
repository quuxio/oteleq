# Usefulness and adoption

## Assessment

Review date: 9 October 2026. oteleq provides a useful foundation for an instrumentation regression gate. Its strongest adoption argument is a reproducible comparison tied to concrete workloads, observed effects, instrumented activity and explicit gaps. Repeated independent lanes and conservative incomplete verdicts support that argument.

The current implementation is an early slice. Diagnostic observers now supply real fixed-workload executions for all eight languages, alongside the Python task example. The Rust comparator validates their captured byte channels and instrumentation witnesses. The [scalar generator](automatic-generation.md) now inventories all recognised selected files, generates executable tests for supported functions and observes scalar globals plus supported Python/Node object graphs. Arbitrary build graphs, factories, receivers and shipping-artefact qualification remain unavailable. A passing stdout/stderr comparison cannot establish unchanged hidden state. The process will provide stronger reassurance as those observations and real application workloads become available.

| Use | Current value |
| --- | --- |
| Detect a stable change in captured application output or a declared effect channel | Implemented, with repeat and completeness checks |
| Confirm expected function spans arrived without reported runtime/export loss | Implemented for fixed diagnostic workloads across all eight languages; new producers need qualification |
| Protect an otelc change with a retained, reproducible example | Useful now within the diagnostic scope |
| Generate repeatable tests and detect supported state mutations | Implemented for accessible scalar callables across all eight languages; unsupported functions/roots fail the strict gate |
| Automatically test every function or detect arbitrary global/instance mutation | Still beyond the qualified scope; factories, build context and additional observers are needed |
| Reassure a team about the exact binary or managed artefact it deploys | Requires production-workload provenance and observers that are still planned |

## Adoption priorities

First make existing representative workloads easy to compare against the actual baseline and instrumented artefacts. Extend the fixed diagnostic providers to bounded, configurable execution for real application workloads across all eight languages. Existing tests, CLI scenarios and fixture services can supply useful concrete cases alongside the bounded scalar generator. Keep production-workload and unit-harness evidence visibly separate.

Next implement typed before/after receiver, argument and global state with explicit alias/cycle and unsupported-root handling. Seed cases with intentional instrumentation defects that change state while preserving return values, so the observer demonstrates that it can catch the relevant regression. Extend the syntax inventory and scalar generation with reviewed factories, preconditions and build-aware discovery; keep the existing inventory gaps visible.

Off/fault lanes and performance budgets strengthen the process when their actual adapter capabilities are qualified. Two repeats screen for obvious instability; they do not establish stability across every schedule or input. Increase repetitions for suitable workloads and retain every attempt. Avoid treating generated test counts or matching business bugs in both variants as evidence of general application correctness.

## Review fixes

The review reproduced passing results for duplicate loss keys and an empty loss map. Those now fail. Channel/function/count maps also reject duplicate keys, preserving the strict input contract. The observers account for queued trees, retain receiver failures, reject incomplete HTTP bodies and malformed runtime counters, and require distinct valid span identities. Missing Python pending contexts, unsupported runtime schema/language and missing native drain status cannot qualify. Both examples reject unexpected baseline telemetry, share the hardened HTTP receiver and strict JSON decoder, and refuse source-contained temporary parents before probing them. Raw transport manifests and application output remain available when later qualification fails.

Remaining limits are explicit: providers are trusted, dependency contents are not fully fingerprinted, and the fixed diagnostic launchers are not sandboxes or general bounded process-tree executors. The scalar workflow bounds time/output and cleans process groups, with the same trusted-code boundary. The Python task observer qualifies span identity/counts; the eight-language observer additionally checks local parent graphs and declared service/scope/error expectations. Neither qualifies arbitrary telemetry semantics or hidden application state. The broader [roadmap](roadmap.md) still applies.

## Comparator optimisation evidence

Channel membership now uses one sorted set per bundle and direct map-key iteration, removing two temporary sets per attempt. Report storage is reserved once. JSON output uses a buffered writer with an explicit checked flush. Observer executable hashes stream from files and raw OTLP hashing avoids joining all bodies into a second large allocation.

A local synthetic comparison on macOS ARM64, Rust 1.98.1 release builds, used one warmup and 11 alternating runs per binary. Each run captured stdout through a pipe. The resulting JSON bytes and exit codes were identical before and after. These are comparator measurements, not application or instrumentation overhead measurements.

| Synthetic fixture | Before median | After median |
| --- | --- | --- |
| One case, two attempts per lane, different 100,000-byte channels with full JSON differences | 88.8 ms | 13.4 ms |
| 25 cases, 100 attempts per lane, 32 empty channels | 29.9 ms | 29.6 ms |

Buffered output improved the large-difference fixture by about 6.6 times. The many-channel fixture showed little total runtime change, where parsing dominates; fewer allocations are not presented as a general speed claim. Re-measure with representative application evidence before setting a performance budget.
